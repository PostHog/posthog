import { ReadableStream } from 'node:stream/web'
import { TextDecoder, TextEncoder } from 'node:util'

import { NodeKind } from '~/queries/schema/schema-general'

import type { QueryRequest } from '../widgets/chart/vizTypes'
import { BUSY_ERROR, createQueryBatchRunner } from './queryBatchRunner'

const TIME = { from: 'now-7d', to: 'now' }
const SQL: QueryRequest = { query: { language: 'hogql', query: 'select 1 as total' }, time: TIME }
const TRENDS: QueryRequest = {
    query: { language: 'insight', query: { kind: NodeKind.TrendsQuery, series: [] } },
    time: TIME,
}
const LATENCY: QueryRequest = {
    query: { language: 'promql', query: 'histogram_quantile(0.95, sum by (le) (rate(latency_bucket[5m])))' },
    time: TIME,
    legend: 'p95 {{service}}',
}
const DAY_1 = Date.UTC(2026, 10, 1)

interface OpenStream {
    body: any
    push: (text: string) => void
    close: () => void
}

describe('createQueryBatchRunner', () => {
    let streams: OpenStream[]
    let status: number

    beforeEach(() => {
        jest.useFakeTimers()
        Object.assign(globalThis, { TextDecoder, TextEncoder })
        streams = []
        status = 200
        globalThis.fetch = jest.fn(async (_url: string, init: RequestInit) => {
            let controller!: ReadableStreamDefaultController<Uint8Array>
            const stream = new ReadableStream<Uint8Array>({ start: (c) => void (controller = c) })
            streams.push({
                body: JSON.parse(String(init.body)),
                push: (text) => controller.enqueue(new TextEncoder().encode(text)),
                close: () => controller.close(),
            })
            return { ok: status < 400, status, body: status < 400 ? stream : null } as unknown as Response
        }) as unknown as typeof fetch
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    const flush = (): Promise<void> => jest.advanceTimersByTimeAsync(50)
    const answer = (stream: OpenStream, i: number, total: number): void =>
        stream.push(
            `${JSON.stringify({ i, result: { frames: [{ name: null, labels: {}, fields: [{ name: 'total', type: 'number', values: [total] }], meta: {}, hash: 'h' }] } })}\n`
        )
    const totalOf = (total: number): unknown => ({
        frames: [{ fields: [{ name: 'total', type: 'number', values: [total] }] }],
    })

    it('sends the queries asked in one tick as one stream and settles each as its line arrives', async () => {
        const runQuery = createQueryBatchRunner(7)
        const first = runQuery(SQL)
        const second = runQuery(TRENDS)
        void runQuery(LATENCY).catch(() => {})
        await flush()

        expect(globalThis.fetch).toHaveBeenCalledTimes(1)
        expect((globalThis.fetch as jest.Mock).mock.calls[0][0]).toBe('/api/projects/7/dashboard_v2/query_batch/')
        expect((globalThis.fetch as jest.Mock).mock.calls[0][1].headers).not.toHaveProperty('Accept')
        expect(streams[0].body).toEqual({
            format: 'frames',
            queries: [
                { target: { refId: '0', language: 'hogql', query: 'select 1 as total' }, time: TIME },
                { target: { refId: '1', language: 'query', query: '{"kind":"TrendsQuery","series":[]}' }, time: TIME },
                {
                    target: { refId: '2', language: 'promql', query: LATENCY.query.query, legend: 'p95 {{service}}' },
                    time: TIME,
                },
            ],
        })

        const frame = {
            name: null,
            labels: {},
            fields: [
                { name: 'day', type: 'time', unit: 'date', values: [DAY_1] },
                { name: 'total', type: 'number', unit: 's', values: [42] },
            ],
            meta: {},
            hash: 'h',
        }
        streams[0].push(
            `${JSON.stringify({ i: 1, result: { frames: [frame], cache: { fetchedAt: '2026-11-01T00:00:00Z', stale: true } } })}\n`
        )

        await expect(second).resolves.toEqual({
            frames: [
                {
                    fields: [
                        { name: 'day', type: 'time', values: ['2026-11-01'] },
                        { name: 'total', type: 'number', values: [42], unit: 's' },
                    ],
                },
            ],
            fetchedAt: '2026-11-01T00:00:00Z',
            stale: true,
        })

        streams[0].push(`${JSON.stringify({ i: 0, error: 'Query timed out' })}\n`)
        await expect(first).rejects.toThrow('Query timed out')
    })

    it('rejects the queries a stream ended without answering', async () => {
        const runQuery = createQueryBatchRunner(7)
        const result = runQuery(SQL)
        await flush()
        streams[0].close()

        await expect(result).rejects.toThrow('No answer came back for this query')
    })

    it('sends charts that mount across ticks as one stream and holds later asks until it ends', async () => {
        const runQuery = createQueryBatchRunner(7)
        const first = runQuery(SQL)
        await jest.advanceTimersByTimeAsync(0)
        const second = runQuery(TRENDS)
        await jest.advanceTimersByTimeAsync(0)
        const third = runQuery(SQL)
        await flush()

        expect(globalThis.fetch).toHaveBeenCalledTimes(1)
        expect(streams[0].body.queries).toHaveLength(3)

        const late = runQuery(TRENDS)
        await flush()
        expect(globalThis.fetch).toHaveBeenCalledTimes(1)

        answer(streams[0], 2, 3)
        answer(streams[0], 0, 1)
        answer(streams[0], 1, 2)
        streams[0].close()
        await expect(Promise.all([first, second, third])).resolves.toEqual([totalOf(1), totalOf(2), totalOf(3)])
        await flush()

        expect(globalThis.fetch).toHaveBeenCalledTimes(2)
        expect(streams[1].body.queries).toEqual([
            { target: { refId: '0', language: 'query', query: '{"kind":"TrendsQuery","series":[]}' }, time: TIME },
        ])
        answer(streams[1], 0, 4)
        await expect(late).resolves.toEqual(totalOf(4))
    })

    it('asks once more for a query answered busy, a second after the stream ends', async () => {
        const runQuery = createQueryBatchRunner(7)
        const result = runQuery(SQL)
        await flush()
        streams[0].push(`${JSON.stringify({ i: 0, error: BUSY_ERROR })}\n`)
        streams[0].close()
        await flush()
        expect(globalThis.fetch).toHaveBeenCalledTimes(1)

        await jest.advanceTimersByTimeAsync(1000)
        expect(globalThis.fetch).toHaveBeenCalledTimes(2)
        streams[1].push(`${JSON.stringify({ i: 0, error: BUSY_ERROR })}\n`)

        await expect(result).rejects.toThrow(BUSY_ERROR)
    })

    it('asks again when the endpoint is busy with earlier batches', async () => {
        status = 429
        const runQuery = createQueryBatchRunner(7)
        const result = runQuery(SQL)
        await flush()
        status = 200

        await jest.advanceTimersByTimeAsync(1000)
        expect(globalThis.fetch).toHaveBeenCalledTimes(2)
        streams[1].push(`${JSON.stringify({ i: 0, error: 'done' })}\n`)

        await expect(result).rejects.toThrow('done')
    })
})
