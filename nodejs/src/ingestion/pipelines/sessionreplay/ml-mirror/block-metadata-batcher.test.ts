import { S3Client } from '@aws-sdk/client-s3'
import { ParquetReader } from '@dsnp/parquetjs'
import sodium from 'libsodium-wrappers'
import { Message } from 'node-rdkafka'

import { parseJSON } from '~/common/utils/json-parse'

import { BlockMetadataBatcher, KeyedRecordReader, OffsetStore } from './block-metadata-batcher'
import { BlockMetadataParquetStore } from './block-metadata-parquet-store'
import { MlBlockMetadataRow } from './block-metadata-row'
import { MlDataKey } from './keys/crypto'
import { decryptEnvelope } from './keys/envelope-testing'
import { MlKeyReader } from './keys/reader'
import { sessionKeyId, tableKeyString } from './keys/schema'
import { MlDecodedMessage, MlKafkaTransport, mlKafkaRecord } from './keys/transport'

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

// Starts at 2026-09-22T12:00:00Z, after the v3 cutoff.
const V3_SESSION = '01a0c8fc-b600-7000-8000-000000000003'

const v3Msg = (offset: number, value: unknown = { ...row(V3_SESSION), team_id: '7', format_version: 2 }): Message =>
    ({
        ...msg(offset, 0, Buffer.from(JSON.stringify(value))),
        headers: [{ ai_research_ingestion_version: Buffer.from('2') }],
    }) as unknown as Message

describe('BlockMetadataBatcher', () => {
    let store: jest.Mocked<BlockMetadataParquetStore>
    let offsets: jest.Mocked<OffsetStore>

    const makeBatcher = (flushIntervalMs: number, maxRows: number, startMs = 0): BlockMetadataBatcher =>
        new BlockMetadataBatcher(store, offsets, { flushIntervalMs, maxRows }, startMs)

    beforeEach(() => {
        store = {
            write: jest.fn().mockResolvedValue(undefined),
            writePlainV3: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<BlockMetadataParquetStore>
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

    it.each([
        { storage: 'legacy', message: msg(0), write: 'write' as const },
        { storage: 'plain v3', message: v3Msg(0), write: 'writePlainV3' as const },
    ])(
        'does not store offsets when the $storage write fails, and the retry writes the same rows',
        async ({ message, write }) => {
            store[write].mockRejectedValueOnce(new Error('s3 down'))
            const batcher = makeBatcher(60_000, 1)
            await expect(batcher.handleBatch([message], 0)).rejects.toThrow('s3 down')
            expect(offsets.offsetsStore).not.toHaveBeenCalled()

            await batcher.flush(1)
            expect(store[write]).toHaveBeenCalledTimes(2)
            expect(store[write].mock.calls[1][0]).toHaveLength(1)
            expect(offsets.offsetsStore).toHaveBeenCalledWith([{ topic: 'ml_block_metadata', partition: 0, offset: 1 }])
        }
    )

    it('keeps the offsets for the next flush when storing them fails, without writing or counting the rows again', async () => {
        offsets.offsetsStore.mockImplementationOnce(() => {
            throw new Error('Local: Erroneous state')
        })
        const batcher = new BlockMetadataBatcher(
            store,
            offsets,
            { flushIntervalMs: 60_000, maxRows: 1_000, maxBytes: msg(0).value!.length * 2 },
            0
        )
        await expect(batcher.handleBatch([msg(0), msg(1)], 0)).rejects.toThrow('Local: Erroneous state')

        await batcher.handleBatch([msg(2, 1)], 0)
        expect(store.write).toHaveBeenCalledTimes(1)
        await batcher.flush(1)
        expect(store.write.mock.calls.map(([rows]) => rows.map((stored) => stored.session_id))).toEqual([
            ['s0', 's1'],
            ['s2'],
        ])
        expect(offsets.offsetsStore.mock.calls).toEqual([
            [[{ topic: 'ml_block_metadata', partition: 0, offset: 2 }]],
            [
                [
                    { topic: 'ml_block_metadata', partition: 0, offset: 2 },
                    { topic: 'ml_block_metadata', partition: 1, offset: 3 },
                ],
            ],
        ])
    })

    it('counts the bytes of a batch whose key read overlaps a flush toward the flush that takes its rows', async () => {
        const asLegacyRows = (messages: Message[]): MlDecodedMessage[] =>
            messages.map((message) => ({ message, original: message }))
        const firstKeyRead = Promise.withResolvers<MlDecodedMessage[]>()
        const keyManager: KeyedRecordReader = {
            read: jest
                .fn()
                .mockReturnValueOnce(firstKeyRead.promise)
                .mockImplementation((messages: Message[]) => Promise.resolve(asLegacyRows(messages))),
        }
        const batcher = new BlockMetadataBatcher(
            store,
            offsets,
            { flushIntervalMs: 60_000, maxRows: 1_000, maxBytes: msg(0).value!.length * 2 },
            0,
            keyManager
        )

        const batchInKeyRead = batcher.handleBatch([msg(0)], 0)
        await batcher.flush(0)
        firstKeyRead.resolve(asLegacyRows([msg(0)]))
        await batchInKeyRead
        await batcher.handleBatch([msg(1)], 0)
        expect(store.write).toHaveBeenCalledTimes(1)
        expect(store.write.mock.calls[0][0].map((stored) => stored.session_id)).toEqual(['s0', 's1'])
    })

    describe.each([
        { storage: 'legacy', write: 'write' as const, message: (offset: number) => msg(offset) },
        { storage: 'plain v3', write: 'writePlainV3' as const, message: (offset: number) => v3Msg(offset) },
    ])('while a $storage flush is writing', ({ write, message }) => {
        let firstWriteStarted: PromiseWithResolvers<void>
        let firstWrite: PromiseWithResolvers<void>
        let writtenRowCounts: number[]

        beforeEach(() => {
            firstWriteStarted = Promise.withResolvers<void>()
            firstWrite = Promise.withResolvers<void>()
            writtenRowCounts = []
            store[write].mockImplementation((rows) => {
                writtenRowCounts.push(rows.length)
                if (writtenRowCounts.length > 1) {
                    return Promise.resolve()
                }
                firstWriteStarted.resolve()
                return firstWrite.promise
            })
        })

        it('keeps a batch that arrives, and stores only the offsets of the rows it wrote', async () => {
            const batcher = makeBatcher(60_000, 1_000)
            await batcher.handleBatch([message(0)], 0)

            const shutdownFlush = batcher.flush(0)
            await firstWriteStarted.promise
            await batcher.handleBatch([message(1)], 0)
            firstWrite.resolve()
            await shutdownFlush
            expect(offsets.offsetsStore.mock.calls).toEqual([
                [[{ topic: 'ml_block_metadata', partition: 0, offset: 1 }]],
            ])

            await batcher.flush(1)
            expect(writtenRowCounts).toEqual([1, 1])
            expect(offsets.offsetsStore).toHaveBeenLastCalledWith([
                { topic: 'ml_block_metadata', partition: 0, offset: 2 },
            ])
        })

        it('holds a second flush until the first fails, then writes both batches and stores their offsets', async () => {
            const batcher = makeBatcher(60_000, 2)
            await batcher.handleBatch([message(0)], 0)

            const shutdownFlush = batcher.flush(0)
            await firstWriteStarted.promise
            const batchAtRowLimit = batcher.handleBatch([message(1), message(2)], 0)
            await new Promise((resolve) => setImmediate(resolve))
            expect(offsets.offsetsStore).not.toHaveBeenCalled()

            firstWrite.reject(new Error('s3 down'))
            await expect(shutdownFlush).rejects.toThrow('s3 down')
            await batchAtRowLimit
            expect(writtenRowCounts).toEqual([1, 3])
            expect(offsets.offsetsStore.mock.calls).toEqual([
                [[{ topic: 'ml_block_metadata', partition: 0, offset: 3 }]],
            ])
        })
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
            new BlockMetadataParquetStore(s3, { v2: 'bucket', v3: 'ml-bucket-v3' }, 'block-metadata'),
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

    it.each([
        { storage: 'legacy', message: skippedMsg(7, 0) },
        { storage: 'plain v3', message: v3Msg(7, { session_id: V3_SESSION, team_id: '7', format_version: 2 }) },
    ])(
        'commits offsets for a skipped-only $storage batch without writing (so it does not replay forever)',
        async ({ message }) => {
            const batcher = makeBatcher(1_000, 1_000_000, 0)
            await batcher.handleBatch([message], 1_000) // all rows dropped by the parser, but offset must advance

            expect(store.write).not.toHaveBeenCalled()
            expect(store.writePlainV3).not.toHaveBeenCalled()
            expect(offsets.offsetsStore).toHaveBeenCalledTimes(1)
            expect(offsets.offsetsStore.mock.calls[0][0]).toEqual([
                { topic: 'ml_block_metadata', partition: 0, offset: 8 },
            ])
        }
    )
})
