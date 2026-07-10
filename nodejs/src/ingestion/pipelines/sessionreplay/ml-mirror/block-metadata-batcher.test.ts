import { Message } from 'node-rdkafka'

import { BlockMetadataBatcher, OffsetStore } from './block-metadata-batcher'
import { BlockMetadataParquetStore } from './block-metadata-parquet-store'
import { MlBlockMetadataRow } from './block-metadata-row'

const row = (sessionId: string): MlBlockMetadataRow => ({
    session_id: sessionId,
    team_id: 't1',
    distinct_id: 'd1',
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

    it('accumulates across batches and flushes once at the row cap', async () => {
        const batcher = makeBatcher(60_000, 3)
        await batcher.handleBatch([msg(0), msg(1)], 0)
        expect(store.write).not.toHaveBeenCalled() // 2 < 3, still buffered

        await batcher.handleBatch([msg(2), msg(3)], 0)
        expect(store.write).toHaveBeenCalledTimes(1)
        expect(store.write.mock.calls[0][0]).toHaveLength(4) // all four rolled into one object
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
