import { S3Client } from '@aws-sdk/client-s3'
import { ParquetReader } from '@dsnp/parquetjs'
import sodium from 'libsodium-wrappers'
import { Message } from 'node-rdkafka'

import { parseJSON } from '~/common/utils/json-parse'

import { BlockMetadataBatcher, OffsetStore } from './block-metadata-batcher'
import { BlockMetadataParquetStore } from './block-metadata-parquet-store'
import { MlBlockMetadataRow } from './block-metadata-row'
import { MlDataKey, decryptEnvelope } from './keys/crypto'
import { MlKeyReader } from './keys/reader'
import { sessionKeyId, tableKeyString } from './keys/schema'
import { MlKafkaTransport, mlKafkaRecord } from './keys/transport'

const row = (sessionId: string): MlBlockMetadataRow => ({
    session_id: sessionId,
    team_id: 't1',
    block_url: 's3://b/k?range=bytes=0-9',
    block_s3_key: 's3://b/k',
    block_byte_start: 0,
    block_byte_end: 9,
    block_length: 10,
    first_ts_ms: 1_000,
    last_ts_ms: 2_000,
    event_count: 1,
    message_count: 1,
    click_count: 0,
    keypress_count: 0,
    mouse_activity_count: 0,
    active_milliseconds: 0,
    console_log_count: 0,
    console_warn_count: 0,
    console_error_count: 0,
    size: 10,
    first_url: null,
    urls: [],
    snapshot_source: null,
    snapshot_library: null,
    retention_period_days: null,
})

const msg = (offset: number, partition = 0, value: Buffer = Buffer.from(JSON.stringify(row(`s${offset}`)))): Message =>
    ({ topic: 'ml_block_metadata', partition, offset, value }) as unknown as Message

/** A message whose value parses as JSON but isn't a valid row, so the parser drops it (offsets still advance). */
const skippedMsg = (offset: number, partition = 0): Message =>
    msg(offset, partition, Buffer.from(JSON.stringify({ session_id: `s${offset}` })))

describe('BlockMetadataBatcher', () => {
    let store: jest.Mocked<BlockMetadataParquetStore>
    let offsets: jest.Mocked<OffsetStore>

    const makeBatcher = (flushIntervalMs: number, maxRows: number, startMs = 0): BlockMetadataBatcher =>
        new BlockMetadataBatcher(store, offsets, { flushIntervalMs, maxRows }, startMs)

    beforeEach(() => {
        store = { write: jest.fn().mockResolvedValue(undefined) } as unknown as jest.Mocked<BlockMetadataParquetStore>
        offsets = { offsetsStore: jest.fn() }
    })

    it.each(['rows', 'bytes'])('accumulates across batches and flushes once at the %s cap', async (limit) => {
        const batcher = new BlockMetadataBatcher(
            store,
            offsets,
            {
                flushIntervalMs: 60_000,
                maxRows: limit === 'rows' ? 3 : 1000,
                maxBytes: limit === 'bytes' ? msg(0).value!.length * 3 : undefined,
            },
            0
        )
        await batcher.handleBatch([msg(0), msg(1)], 0)
        expect(store.write).not.toHaveBeenCalled() // 2 < 3, still buffered

        await batcher.handleBatch([msg(2), msg(3)], 0)
        expect(store.write).toHaveBeenCalledTimes(1)
        expect(store.write.mock.calls[0][0]).toHaveLength(4) // all four rolled into one object
        await batcher.handleBatch([msg(4)], 0)
        expect(store.write).toHaveBeenCalledTimes(1)
    })

    it('flushes the buffer once the interval elapses, even on an empty poll', async () => {
        const batcher = makeBatcher(1_000, 1_000_000, 0)
        await batcher.handleBatch([msg(0)], 500)
        expect(store.write).not.toHaveBeenCalled()

        await batcher.handleBatch([], 1_000) // empty poll past the interval
        expect(store.write).toHaveBeenCalledTimes(1)
        expect(store.write.mock.calls[0][0]).toHaveLength(1)
    })

    it('stores the next offset per partition only after a successful write', async () => {
        const batcher = makeBatcher(60_000, 2)
        await batcher.handleBatch([msg(5, 0), msg(9, 1)], 0)

        expect(offsets.offsetsStore).toHaveBeenCalledTimes(1)
        const stored = offsets.offsetsStore.mock.calls[0][0].sort((a, b) => a.partition - b.partition)
        expect(stored).toEqual([
            { topic: 'ml_block_metadata', partition: 0, offset: 6 },
            { topic: 'ml_block_metadata', partition: 1, offset: 10 },
        ])
    })

    it('does not store offsets when the write fails (so the window replays)', async () => {
        store.write.mockRejectedValueOnce(new Error('s3 down'))
        const batcher = makeBatcher(60_000, 1)
        await expect(batcher.handleBatch([msg(0)], 0)).rejects.toThrow('s3 down')
        expect(offsets.offsetsStore).not.toHaveBeenCalled()
    })

    it('keeps v2 offsets pending until the encrypted eval index upload succeeds', async () => {
        await sodium.ready
        const sessionId = '01a0a4f0-3200-7000-8000-000000000001'
        const timestamp = Date.parse('2026-09-15T12:00:01Z')
        const key: MlDataKey = {
            identity: { teamId: 7, organizationId: 'test-org', sessionId },
            plaintext: Buffer.alloc(32, 7),
            wrapped: Buffer.from('wrapped'),
        }
        const reader = {
            read: jest.fn(() => Promise.resolve(new Map([[tableKeyString(sessionKeyId(7, sessionId)), key]]))),
        } as unknown as MlKeyReader
        const metadata: MlBlockMetadataRow = {
            ...row(sessionId),
            team_id: '7',
            format_version: 2,
            first_ts_ms: timestamp,
            last_ts_ms: timestamp,
            replay_index_entries: [
                { kind: 'json_ld', eventIndex: 0, eventTimestamp: timestamp, windowId: 'w1', rootTypes: ['Product'] },
            ],
        }
        const encrypted = mlKafkaRecord(
            '2',
            Buffer.from(JSON.stringify({ ...metadata, distinct_id: 'legacy-user', distinctId: 'unexpected-user' }))
        )
        const message = {
            ...msg(0),
            value: encrypted.value,
            headers: Object.entries(encrypted.headers).map(([name, value]) => ({ [name]: Buffer.from(value) })),
        }
        const s3 = {
            send: jest.fn().mockRejectedValueOnce(new Error('index upload failed')).mockResolvedValue({}),
        } as unknown as S3Client
        const batcher = new BlockMetadataBatcher(
            new BlockMetadataParquetStore(s3, 'bucket', 'block-metadata'),
            offsets,
            { flushIntervalMs: 1000, maxRows: 1 },
            0,
            new MlKafkaTransport(reader)
        )
        await expect(batcher.handleBatch([message], 0)).rejects.toThrow('index upload failed')
        expect(offsets.offsetsStore).not.toHaveBeenCalled()
        await batcher.flush(1)
        expect(offsets.offsetsStore).toHaveBeenCalledWith([{ topic: 'ml_block_metadata', partition: 0, offset: 1 }])
        const body = (jest.mocked(s3.send).mock.calls.at(-1)![0].input as { Body: Buffer }).Body
        const parquet = await ParquetReader.openBuffer(body)
        const stored = (await parquet.getCursor().next()) as { payload: Buffer }
        const payload = parseJSON(decryptEnvelope(key, parseJSON(stored!.payload.toString()), 'metadata').toString())
        expect(payload).toEqual(metadata)
        await parquet.close()
        expect(jest.mocked(s3.send).mock.calls.map(([command]) => (command.input as { Key: string }).Key)).toEqual([
            expect.stringContaining('block-metadata-replay-index/v2/2026-09/kind=json_ld/'),
            expect.stringContaining('block-metadata-replay-index/v2/2026-09/kind=json_ld/'),
            expect.stringContaining('block-metadata/v2/2026-09/'),
        ])
    })

    it('starts a fresh window after flushing', async () => {
        const batcher = makeBatcher(1_000, 1_000_000, 0)
        await batcher.handleBatch([msg(0)], 1_000) // flushes (interval elapsed)
        expect(store.write).toHaveBeenCalledTimes(1)

        await batcher.handleBatch([msg(1)], 1_500) // new window, interval not elapsed
        expect(store.write).toHaveBeenCalledTimes(1)
    })

    it('commits offsets for a skipped-only batch without writing (so it does not replay forever)', async () => {
        const batcher = makeBatcher(1_000, 1_000_000, 0)
        await batcher.handleBatch([skippedMsg(7, 0)], 1_000) // all rows dropped by the parser, but offset must advance

        expect(store.write).not.toHaveBeenCalled()
        expect(offsets.offsetsStore).toHaveBeenCalledTimes(1)
        expect(offsets.offsetsStore.mock.calls[0][0]).toEqual([{ topic: 'ml_block_metadata', partition: 0, offset: 8 }])
    })
})
