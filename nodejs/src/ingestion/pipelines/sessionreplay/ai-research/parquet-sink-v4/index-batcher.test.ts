import { PutObjectCommandInput, S3Client } from '@aws-sdk/client-s3'
import { ParquetReader } from '@dsnp/parquetjs'
import { Message } from 'node-rdkafka'
import { register } from 'prom-client'

import { OffsetStore } from '~/ingestion/pipelines/sessionreplay/shared/capture-watermark'

import { IndexBatcher, IndexBatcherOptions } from './index-batcher'
import { BLOCK_INDEX_COLUMNS, V4Index } from './index-columns'
import { IndexParquetStore } from './index-parquet-store'

const TOPIC = 'ai_research_v4_index'

function blockRow(sessionId: string): Record<string, unknown> {
    const row: Record<string, unknown> = {}
    for (const column of BLOCK_INDEX_COLUMNS) {
        row[column.name] =
            'repeated' in column || 'list' in column
                ? []
                : column.optional
                  ? null
                  : column.type === 'UTF8'
                    ? 'x'
                    : column.type === 'BOOLEAN'
                      ? false
                      : 1
    }
    return {
        ...row,
        session_id: sessionId,
        moments: [{ kind: 'click', window_id: 'w1', ts_ms: 1_000, event_index: 3 }],
        url_fingerprints: ['b08517cee3ff5ecc'],
        window_ids: ['w1'],
    }
}

const imageRow = (imageRef: string): Record<string, unknown> => ({
    team_id: 7,
    key_month: '2026-10',
    image_ref: imageRef,
    pack_s3_key: 'images/packs/dt=2026-10-15/7/1-0',
    byte_start: 0,
    byte_end: 99,
    mime: 'image/png',
    byte_size: 60,
})

function message(
    offset: number,
    index: string,
    writeDay: string,
    value: unknown,
    partition = 0,
    raw?: string
): Message {
    return {
        topic: TOPIC,
        partition,
        offset,
        value: Buffer.from(raw ?? JSON.stringify(value)),
        headers: [{ 'ml-index': Buffer.from(index) }, { 'ml-write-day': Buffer.from(writeDay) }],
    } as unknown as Message
}

async function readColumn(body: Buffer, column: string): Promise<unknown[]> {
    const reader = await ParquetReader.openBuffer(body)
    const cursor = reader.getCursor()
    const values: unknown[] = []
    for (let record = await cursor.next(); record; record = await cursor.next()) {
        values.push((record as Record<string, unknown>)[column])
    }
    await reader.close()
    return values
}

async function rejected(reason: string): Promise<number> {
    const metric = await register.getSingleMetric('ai_research_v4_parquet_sink_rows_rejected_total')!.get()
    return metric.values.find((value) => value.labels.reason === reason)?.value ?? 0
}

describe('IndexBatcher', () => {
    let puts: PutObjectCommandInput[]
    let send: jest.Mock
    let offsets: jest.Mocked<OffsetStore>

    const makeBatcher = (options: Partial<IndexBatcherOptions> = {}) =>
        new IndexBatcher(
            new IndexParquetStore({ send } as unknown as S3Client, 'rrweb-v4', 1_000),
            offsets,
            { flushIntervalMs: 600_000, maxRows: 1_000, maxBytes: 1024 * 1024, ...options },
            0
        )

    const keysOf = (index: V4Index): string[] =>
        puts.map((put) => put.Key!).filter((key) => key.startsWith(`index/${index}/`))

    beforeEach(() => {
        puts = []
        send = jest.fn((command: { input: PutObjectCommandInput }) => {
            puts.push(command.input)
            return Promise.resolve({})
        })
        offsets = { offsetsStore: jest.fn() }
    })

    it('writes one file per index and write day, then stores the next offset of each partition', async () => {
        const batcher = makeBatcher({ maxRows: 4 })
        await batcher.handleBatch(
            [
                message(10, 'blocks', '2026-10-15', blockRow('s1')),
                message(11, 'images', '2026-10-15', imageRow('image:v4:7:2026-10:a')),
                message(5, 'blocks', '2026-10-16', blockRow('s3'), 1),
            ],
            1
        )
        expect(send).not.toHaveBeenCalled()

        await batcher.handleBatch([message(12, 'blocks', '2026-10-15', blockRow('s2'))], 2)

        expect(puts.map((put) => [put.Bucket, put.IfNoneMatch])).toEqual(Array(3).fill(['rrweb-v4', '*']))
        const [day15, day16] = keysOf('blocks').sort()
        expect(day15).toMatch(/^index\/blocks\/dt=2026-10-15\/\d+-[0-9a-f]{16}\.parquet$/)
        expect(day16).toMatch(/^index\/blocks\/dt=2026-10-16\//)
        expect(keysOf('images')).toEqual([expect.stringMatching(/^index\/images\/dt=2026-10-15\//)])
        const body = (key: string): Buffer => puts.find((put) => put.Key === key)!.Body as Buffer
        expect(await readColumn(body(day15), 'session_id')).toEqual(['s1', 's2'])
        expect(await readColumn(body(day16), 'session_id')).toEqual(['s3'])
        expect(await readColumn(body(keysOf('images')[0]), 'image_ref')).toEqual(['image:v4:7:2026-10:a'])
        expect(offsets.offsetsStore).toHaveBeenCalledTimes(1)
        expect(offsets.offsetsStore.mock.calls[0][0]).toEqual(
            expect.arrayContaining([
                { topic: TOPIC, partition: 0, offset: 13 },
                { topic: TOPIC, partition: 1, offset: 6 },
            ])
        )
    })

    it.each([
        ['value that is not JSON', 'parse_failed', message(1, 'blocks', '2026-10-15', null, 0, '{not json')],
        [
            'count above the INT32 range',
            'invalid_row',
            message(1, 'blocks', '2026-10-15', { ...blockRow('s1'), clicks: 2 ** 31 }),
        ],
        [
            'moment index above the INT32 range',
            'invalid_row',
            message(1, 'blocks', '2026-10-15', {
                ...blockRow('s1'),
                moments: [{ kind: 'click', window_id: 'w1', ts_ms: 1_000, event_index: 2 ** 31 }],
            }),
        ],
        [
            'flag that is not a boolean',
            'invalid_row',
            message(1, 'blocks', '2026-10-15', { ...blockRow('s1'), moments_truncated: 1 }),
        ],
        [
            'flush row count above the INT32 range',
            'invalid_row',
            message(1, 'blocks', '2026-10-15', { ...blockRow('s1'), flush_row_count: 2 ** 31 }),
        ],
        [
            'url fingerprint that is not a string',
            'invalid_row',
            message(1, 'blocks', '2026-10-15', { ...blockRow('s1'), url_fingerprints: [7] }),
        ],
        [
            'window id list with a null item',
            'invalid_row',
            message(1, 'blocks', '2026-10-15', { ...blockRow('s1'), window_ids: ['w1', null] }),
        ],
        [
            'window ids that are not a list',
            'invalid_row',
            message(1, 'blocks', '2026-10-15', { ...blockRow('s1'), window_ids: 'w1' }),
        ],
        [
            'missing urls_truncated flag',
            'invalid_row',
            message(1, 'blocks', '2026-10-15', { ...blockRow('s1'), urls_truncated: undefined }),
        ],
        [
            'moment without its fields',
            'invalid_row',
            message(1, 'blocks', '2026-10-15', { ...blockRow('s1'), moments: [{ kind: 'click' }] }),
        ],
        ['block row sent as an image row', 'invalid_row', message(1, 'images', '2026-10-15', blockRow('s1'))],
        ['unknown index header', 'unknown_index', message(1, 'sessions', '2026-10-15', blockRow('s1'))],
        ['write day that is not a date', 'invalid_write_day', message(1, 'blocks', '2026-02-30', blockRow('s1'))],
    ])('rejects a row with a %s as %s, and still moves past it', async (_name, reason, bad) => {
        const before = await rejected(reason)
        const batcher = makeBatcher({ flushIntervalMs: 1_000 })

        await batcher.handleBatch([bad], 1_000)

        expect(await rejected(reason)).toBe(before + 1)
        expect(send).not.toHaveBeenCalled()
        expect(offsets.offsetsStore).toHaveBeenCalledWith([{ topic: TOPIC, partition: 0, offset: 2 }])
    })

    it.each([
        ['a timestamp outside the JS-safe range', { ...blockRow('s1'), first_ts_ms: 2 ** 53 }, 'first_ts_ms'],
        [
            'a moment index above the INT32 range',
            { ...blockRow('s1'), moments: [{ kind: 'click', window_id: 'w1', ts_ms: 1_000, event_index: 2 ** 31 }] },
            'moments.event_index',
        ],
    ])('counts a row rejected for %s by the column that failed', async (_name, row, column) => {
        const counted = async (): Promise<number> => {
            const metric = await register.getSingleMetric('ai_research_v4_parquet_sink_invalid_columns_total')!.get()
            return (
                metric.values.find((value) => value.labels.index === 'blocks' && value.labels.column === column)
                    ?.value ?? 0
            )
        }
        const before = await counted()

        await makeBatcher().handleBatch([message(1, 'blocks', '2026-10-15', row)], 1)

        expect(await counted()).toBe(before + 1)
    })

    it('stores no offsets when a write fails, and writes only the unwritten files on the next flush', async () => {
        const batcher = makeBatcher()
        await batcher.handleBatch(
            [
                message(1, 'blocks', '2026-10-15', blockRow('s1')),
                message(2, 'images', '2026-10-15', imageRow('image:v4:7:2026-10:a')),
            ],
            1
        )
        send.mockImplementationOnce((command: { input: PutObjectCommandInput }) => {
            puts.push(command.input)
            return Promise.resolve({})
        }).mockRejectedValueOnce(new Error('s3 down'))

        await expect(batcher.flush(2)).rejects.toThrow('s3 down')
        expect(offsets.offsetsStore).not.toHaveBeenCalled()
        expect(keysOf('blocks')).toHaveLength(1)

        await batcher.flush(3)
        expect(keysOf('blocks')).toHaveLength(1)
        expect(keysOf('images')).toHaveLength(1)
        expect(offsets.offsetsStore).toHaveBeenCalledWith([{ topic: TOPIC, partition: 0, offset: 3 }])
    })

    it('reports health while a flush waits on a slow upload, and stops when the flush ends', async () => {
        jest.useFakeTimers({ doNotFake: ['nextTick', 'setImmediate', 'queueMicrotask', 'setTimeout', 'clearTimeout'] })
        const heartbeat = jest.fn()
        const batcher = makeBatcher({ heartbeat, heartbeatIntervalMs: 10_000 })
        await batcher.handleBatch([message(1, 'blocks', '2026-10-15', blockRow('s1'))], 1)
        let finishUpload: ((value: unknown) => void) | undefined
        send.mockImplementationOnce(() => new Promise((resolve) => (finishUpload = resolve)))

        const flushed = batcher.flush(2)
        while (!finishUpload) {
            await new Promise((resolve) => setImmediate(resolve))
        }
        jest.advanceTimersByTime(25_000)
        expect(heartbeat).toHaveBeenCalledTimes(2)
        finishUpload({})
        await flushed
        jest.advanceTimersByTime(20_000)

        expect(heartbeat).toHaveBeenCalledTimes(2)
        jest.useRealTimers()
    })

    it('leaves out the rows and offsets of a revoked partition', async () => {
        const batcher = makeBatcher()
        await batcher.handleBatch(
            [
                message(1, 'blocks', '2026-10-15', blockRow('kept')),
                message(7, 'blocks', '2026-10-15', blockRow('gone'), 1),
            ],
            1
        )

        batcher.release([{ topic: TOPIC, partition: 1 }])
        await batcher.flush(2)

        expect(await readColumn(puts[0].Body as Buffer, 'session_id')).toEqual(['kept'])
        expect(offsets.offsetsStore).toHaveBeenCalledWith([{ topic: TOPIC, partition: 0, offset: 2 }])
    })
})
