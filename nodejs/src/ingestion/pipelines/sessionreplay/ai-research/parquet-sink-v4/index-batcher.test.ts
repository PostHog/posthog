import { PutObjectCommandInput, S3Client } from '@aws-sdk/client-s3'
import { ParquetReader } from '@dsnp/parquetjs'
import { Message } from 'node-rdkafka'
import { register } from 'prom-client'

import { parseJSON } from '~/common/utils/json-parse'
import {
    CAPTURE_TIMESTAMP_HEADER,
    CaptureWatermark,
    OffsetStore,
    capturedRecords,
    releasingOffsetStore,
} from '~/ingestion/pipelines/sessionreplay/shared/capture-watermark'

import { IndexBatcher, IndexBatcherOptions } from './index-batcher'
import { BLOCK_INDEX_COLUMNS, V4Index } from './index-columns'
import { indexCapturedData } from './index-message'
import { IndexParquetStore } from './index-parquet-store'
import { IndexWatermarkFiles, WATERMARK_FILE_INTERVAL_MS } from './index-watermark-files'

const TOPIC = 'ai_research_v4_index'
const WALL_CLOCK_MS = 1_790_000_000_000

function blockRow(sessionId: string): Record<string, unknown> {
    const row: Record<string, unknown> = {}
    for (const column of BLOCK_INDEX_COLUMNS) {
        row[column.name] =
            'repeated' in column || 'list' in column || 'elements' in column
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

const captured = (capturedAtMs: number, message: Message): Message => ({
    ...message,
    headers: [...(message.headers ?? []), { [CAPTURE_TIMESTAMP_HEADER]: Buffer.from(String(capturedAtMs)) }],
})

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

async function failedWatermarkWrites(): Promise<number> {
    const metric = await register.getSingleMetric('ai_research_v4_parquet_sink_watermark_writes_total')!.get()
    return (
        metric.values.find((value) => value.labels.index === 'blocks' && value.labels.outcome === 'failed')?.value ?? 0
    )
}

describe('IndexBatcher', () => {
    let puts: PutObjectCommandInput[]
    let send: jest.Mock
    let offsets: jest.Mocked<OffsetStore>
    let watermark: CaptureWatermark

    const makeBatcher = (options: Partial<IndexBatcherOptions> = {}) =>
        new IndexBatcher(
            new IndexParquetStore({ send } as unknown as S3Client, 'rrweb-v4', 1_000),
            releasingOffsetStore(offsets, watermark),
            new IndexWatermarkFiles({ send } as unknown as S3Client, 'rrweb-v4', watermark),
            { flushIntervalMs: 600_000, maxRows: 1_000, maxBytes: 1024 * 1024, ...options },
            0
        )

    const deliver = (batcher: IndexBatcher, messages: Message[], nowMs: number): Promise<void> => {
        watermark.hold(capturedRecords(messages, indexCapturedData))
        return batcher.handleBatch(messages, nowMs)
    }

    const keysOf = (index: V4Index): string[] =>
        puts.map((put) => put.Key!).filter((key) => key.startsWith(`index/${index}/`))

    const watermarkPuts = (): PutObjectCommandInput[] => puts.filter((put) => put.Key!.includes('/_watermarks/'))

    const watermarkFiles = (): Record<string, unknown> =>
        Object.fromEntries(watermarkPuts().map((put) => [put.Key!, parseJSON(put.Body as string)]))

    beforeEach(() => {
        puts = []
        send = jest.fn((command: { input: PutObjectCommandInput }) => {
            puts.push(command.input)
            return Promise.resolve({})
        })
        offsets = { offsetsStore: jest.fn() }
        watermark = new CaptureWatermark('index-batcher-test', 0)
    })

    afterEach(() => {
        jest.restoreAllMocks()
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
            'click target id that is not an integer',
            'invalid_row',
            message(1, 'blocks', '2026-10-15', { ...blockRow('s1'), surfacing_click_target_ids: [1.5] }),
        ],
        [
            'visited url fingerprints that are not a list',
            'invalid_row',
            message(1, 'blocks', '2026-10-15', { ...blockRow('s1'), surfacing_visited_url_fingerprints: 'x' }),
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

    it('writes the watermark files after the index files and the offsets, and never past a row still buffered', async () => {
        jest.spyOn(Date, 'now').mockReturnValue(WALL_CLOCK_MS)
        const steps: string[] = []
        const record = (command: { input: PutObjectCommandInput }): void => {
            puts.push(command.input)
            steps.push(command.input.Key!.replace(/\d+-[0-9a-f]{16}\.parquet$/, '{file}'))
        }
        let finishUpload: ((value: unknown) => void) | undefined
        send.mockImplementation((command: { input: PutObjectCommandInput }) => {
            record(command)
            return Promise.resolve({})
        }).mockImplementationOnce((command: { input: PutObjectCommandInput }) => {
            record(command)
            return new Promise((resolve) => (finishUpload = resolve))
        })
        offsets.offsetsStore.mockImplementation(() => steps.push('store offsets'))
        const batcher = makeBatcher()
        await deliver(
            batcher,
            [
                captured(5_000, message(10, 'blocks', '2026-10-15', blockRow('s1'))),
                captured(4_000, message(11, 'images', '2026-10-15', imageRow('image:v4:7:2026-10:a'))),
            ],
            1
        )

        const flushed = batcher.flush(2)
        while (!finishUpload) {
            await new Promise((resolve) => setImmediate(resolve))
        }
        // The shutdown flush runs while batches still arrive, so this row is buffered but not in the files being written.
        await deliver(batcher, [captured(3_000, message(12, 'blocks', '2026-10-15', blockRow('s2')))], 3)
        finishUpload({})
        await flushed

        expect(steps).toEqual([
            'index/blocks/dt=2026-10-15/{file}',
            'index/images/dt=2026-10-15/{file}',
            'store offsets',
            'index/blocks/_watermarks/partition=0000.json',
            'index/images/_watermarks/partition=0000.json',
        ])
        expect(watermarkFiles()).toEqual({
            'index/blocks/_watermarks/partition=0000.json': {
                partition: 0,
                complete_up_to_capture_ms: 3_000,
                committed_offset: 12,
                written_at_ms: WALL_CLOCK_MS,
            },
            'index/images/_watermarks/partition=0000.json': {
                partition: 0,
                complete_up_to_capture_ms: 4_000,
                committed_offset: 12,
                written_at_ms: WALL_CLOCK_MS,
            },
        })
        expect(watermarkPuts().map((put) => put.IfNoneMatch)).toEqual([undefined, undefined])
    })

    it('rewrites the watermark files once per interval, also on idle polls, and only for partitions it owns', async () => {
        const clock = jest.spyOn(Date, 'now')
        const batcher = makeBatcher()
        const flushAt = async (atMs: number, messages: Message[]): Promise<void> => {
            clock.mockReturnValue(WALL_CLOCK_MS + atMs)
            await deliver(batcher, messages, atMs)
            await batcher.flush(atMs)
        }

        await flushAt(0, [
            captured(1_000, message(1, 'blocks', '2026-10-15', blockRow('s1'))),
            captured(2_000, message(1, 'blocks', '2026-10-15', blockRow('s2'), 1)),
        ])
        batcher.release([{ topic: TOPIC, partition: 1 }])
        await flushAt(WATERMARK_FILE_INTERVAL_MS - 1, [
            captured(3_000, message(2, 'blocks', '2026-10-15', blockRow('s1'))),
        ])
        expect(watermarkPuts()).toHaveLength(2)
        clock.mockReturnValue(WALL_CLOCK_MS + WATERMARK_FILE_INTERVAL_MS)
        await batcher.handleBatch([], WATERMARK_FILE_INTERVAL_MS)

        expect(watermarkPuts().map((put) => put.Key)).toEqual([
            'index/blocks/_watermarks/partition=0000.json',
            'index/blocks/_watermarks/partition=0001.json',
            'index/blocks/_watermarks/partition=0000.json',
        ])
        expect(watermarkFiles()['index/blocks/_watermarks/partition=0000.json']).toEqual({
            partition: 0,
            complete_up_to_capture_ms: 3_000,
            committed_offset: 3,
            written_at_ms: WALL_CLOCK_MS + WATERMARK_FILE_INTERVAL_MS,
        })
    })

    it('aborts the watermark write of a partition revoked while the write is in flight, and keeps the others', async () => {
        const failedBefore = await failedWatermarkWrites()
        const finishWrite = new Map<string, () => void>()
        send.mockImplementation((command: { input: PutObjectCommandInput }, options: { abortSignal: AbortSignal }) => {
            if (!command.input.Key!.includes('/_watermarks/')) {
                puts.push(command.input)
                return Promise.resolve({})
            }
            return new Promise((resolve, reject) => {
                options.abortSignal.addEventListener('abort', () => reject(new Error('aborted')))
                finishWrite.set(command.input.Key!, () => {
                    if (!options.abortSignal.aborted) {
                        puts.push(command.input)
                        resolve({})
                    }
                })
            })
        })
        const batcher = makeBatcher()
        await deliver(
            batcher,
            [
                captured(1_000, message(1, 'blocks', '2026-10-15', blockRow('s1'))),
                captured(2_000, message(1, 'blocks', '2026-10-15', blockRow('s2'), 1)),
            ],
            0
        )

        const flushed = batcher.flush(0)
        while (finishWrite.size < 2) {
            await new Promise((resolve) => setImmediate(resolve))
        }
        batcher.release([{ topic: TOPIC, partition: 1 }])
        for (const finish of finishWrite.values()) {
            finish()
        }
        await flushed

        expect(watermarkPuts().map((put) => put.Key)).toEqual(['index/blocks/_watermarks/partition=0000.json'])
        expect(await failedWatermarkWrites()).toBe(failedBefore)
    })

    it('keeps a flush successful when a watermark write fails, and writes the file on a poll after the interval', async () => {
        const clock = jest.spyOn(Date, 'now').mockReturnValue(WALL_CLOCK_MS)
        const failedBefore = await failedWatermarkWrites()
        send.mockImplementation((command: { input: PutObjectCommandInput }) => {
            if (command.input.Key!.includes('/_watermarks/')) {
                return Promise.reject(new Error('s3 down'))
            }
            puts.push(command.input)
            return Promise.resolve({})
        })
        const batcher = makeBatcher()
        await deliver(batcher, [captured(1_000, message(1, 'blocks', '2026-10-15', blockRow('s1')))], 1)

        await expect(batcher.flush(2)).resolves.toBeUndefined()
        expect(offsets.offsetsStore).toHaveBeenCalledWith([{ topic: TOPIC, partition: 0, offset: 2 }])
        expect(await failedWatermarkWrites()).toBe(failedBefore + 1)

        send.mockImplementation((command: { input: PutObjectCommandInput }) => {
            puts.push(command.input)
            return Promise.resolve({})
        })
        clock.mockReturnValue(WALL_CLOCK_MS + WATERMARK_FILE_INTERVAL_MS)
        await batcher.handleBatch([], 2 + WATERMARK_FILE_INTERVAL_MS - 1)
        expect(watermarkPuts()).toHaveLength(0)
        await batcher.handleBatch([], 2 + WATERMARK_FILE_INTERVAL_MS)

        expect(watermarkFiles()).toEqual({
            'index/blocks/_watermarks/partition=0000.json': {
                partition: 0,
                complete_up_to_capture_ms: 1_000,
                committed_offset: 2,
                written_at_ms: WALL_CLOCK_MS + WATERMARK_FILE_INTERVAL_MS,
            },
        })
    })
})
