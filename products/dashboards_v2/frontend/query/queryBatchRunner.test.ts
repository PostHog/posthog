import { ReadableStream } from 'node:stream/web'
import { TextDecoder, TextEncoder } from 'node:util'
import posthog from 'posthog-js'

import { NodeKind } from '~/queries/schema/schema-general'

import { BUSY_ERROR, MAX_STREAMS, PROJECT_NOT_ALLOWED_ERROR, createQueryBatchRunner } from './queryBatchRunner'
import { QUERY_BATCH_TIMING_EVENT } from './queryBatchTiming'
import type { QueryRequest } from './queryTypes'

const TIME = { from: 'now-7d', to: 'now' }
const SQL: QueryRequest = { query: { language: 'hogql', query: 'select 1 as total' }, time: TIME }
const TRENDS: QueryRequest = {
    query: { language: 'query', query: { kind: NodeKind.TrendsQuery, series: [] } },
    time: TIME,
}
const LATENCY: QueryRequest = {
    query: { language: 'promql', query: 'histogram_quantile(0.95, sum by (le) (rate(latency_bucket[5m])))' },
    time: TIME,
    legend: 'p95 {{service}}',
}
const DAY_1 = Date.UTC(2026, 10, 1)

type OpenStream = {
    url: string
    body: any
    signal: AbortSignal
    push: (text: string) => void
    close: () => void
}

describe('createQueryBatchRunner', () => {
    let streams: OpenStream[]
    let status: number
    let traceresponse: string | null

    beforeEach(() => {
        jest.useFakeTimers()
        Object.assign(globalThis, { TextDecoder, TextEncoder })
        streams = []
        status = 200
        traceresponse = null
        globalThis.fetch = jest.fn(async (url: string, init: RequestInit) => {
            let controller!: ReadableStreamDefaultController<Uint8Array>
            const stream = new ReadableStream<Uint8Array>({ start: (c) => void (controller = c) })
            streams.push({
                url,
                body: JSON.parse(String(init.body)),
                signal: init.signal as AbortSignal,
                push: (text) => controller.enqueue(new TextEncoder().encode(text)),
                close: () => controller.close(),
            })
            return {
                ok: status < 400,
                status,
                headers: { get: (name: string) => (name === 'traceresponse' ? traceresponse : null) },
                body: status < 400 ? stream : null,
            } as unknown as Response
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
        frames: [{ meta: {}, hash: 'h', fields: [{ name: 'total', type: 'number', values: [total] }] }],
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
            labels: { series_index: '0' },
            fields: [
                { name: 'day', type: 'time', unit: 'date', values: [DAY_1] },
                { name: 'total', type: 'number', unit: 's', values: [42], labels: { le: '0.5' } },
            ],
            meta: { interval: 'day', end: DAY_1 },
            hash: 'h',
        }
        streams[0].push(
            `${JSON.stringify({ i: 1, result: { frames: [frame], cache: { fetchedAt: '2026-11-01T00:00:00Z', stale: true } } })}\n`
        )

        await expect(second).resolves.toEqual({
            frames: [
                {
                    labels: { series_index: '0' },
                    meta: { interval: 'day', end: DAY_1 },
                    hash: 'h',
                    fields: [
                        { name: 'day', type: 'time', values: ['2026-11-01'] },
                        { name: 'total', type: 'number', values: [42], unit: 's', labels: { le: '0.5' } },
                    ],
                },
            ],
            fetchedAt: '2026-11-01T00:00:00Z',
            stale: true,
        })

        streams[0].push(`${JSON.stringify({ i: 0, error: 'Query timed out' })}\n`)
        await expect(first).rejects.toThrow('Query timed out')
    })

    it("sends a query that names another project to that project's endpoint, in its own stream", async () => {
        const runQuery = createQueryBatchRunner(7, { allowsProject: (project) => project === 9 })
        const own = runQuery(SQL)
        const other = runQuery({ ...SQL, project: 9 })
        const ownAgain = runQuery(TRENDS)
        await flush()

        expect(streams.map((stream) => [stream.url, stream.body.queries.length])).toEqual([
            ['/api/projects/7/dashboard_v2/query_batch/', 2],
            ['/api/projects/9/dashboard_v2/query_batch/', 1],
        ])
        answer(streams[1], 0, 9)
        answer(streams[0], 1, 2)
        answer(streams[0], 0, 1)
        await expect(other).resolves.toEqual(totalOf(9))
        await expect(own).resolves.toEqual(totalOf(1))
        await expect(ownAgain).resolves.toEqual(totalOf(2))
    })

    it.each([
        ['no check', undefined],
        ['a check that refuses it', (project: number): boolean => project === 9],
    ])('sends nothing for a query that names a project outside the organization, with %s', async (_, allowsProject) => {
        const runQuery = createQueryBatchRunner(7, { allowsProject })
        await expect(runQuery({ ...SQL, project: 8 })).rejects.toThrow(PROJECT_NOT_ALLOWED_ERROR)
        await flush()

        expect(globalThis.fetch).not.toHaveBeenCalled()
    })

    it('rejects the queries a stream ended without answering', async () => {
        const runQuery = createQueryBatchRunner(7)
        const result = runQuery(SQL)
        await flush()
        streams[0].close()

        await expect(result).rejects.toThrow('No answer came back for this query')
    })

    it('sends charts that mount across ticks as one stream, runs up to three streams and holds later asks', async () => {
        const runQuery = createQueryBatchRunner(7)
        const first = runQuery(SQL)
        await jest.advanceTimersByTimeAsync(0)
        const second = runQuery(TRENDS)
        await jest.advanceTimersByTimeAsync(0)
        const third = runQuery(SQL)
        await flush()

        expect(globalThis.fetch).toHaveBeenCalledTimes(1)
        expect(streams[0].body.queries).toHaveLength(3)

        const later = []
        for (let total = 4; total < 4 + MAX_STREAMS; total++) {
            later.push(runQuery(TRENDS))
            await flush()
        }
        expect(globalThis.fetch).toHaveBeenCalledTimes(MAX_STREAMS)

        answer(streams[0], 2, 3)
        answer(streams[0], 0, 1)
        answer(streams[0], 1, 2)
        streams[0].close()
        await expect(Promise.all([first, second, third])).resolves.toEqual([totalOf(1), totalOf(2), totalOf(3)])
        await flush()

        expect(globalThis.fetch).toHaveBeenCalledTimes(MAX_STREAMS + 1)
        expect(streams[MAX_STREAMS].body.queries).toEqual([
            { target: { refId: '0', language: 'query', query: '{"kind":"TrendsQuery","series":[]}' }, time: TIME },
        ])
        for (let stream = MAX_STREAMS; stream >= 1; stream--) {
            answer(streams[stream], 0, 3 + stream)
        }
        await expect(Promise.all(later)).resolves.toEqual(later.map((_, index) => totalOf(4 + index)))
    })

    it('leaves out a query that aborted before its batch was sent', async () => {
        const runQuery = createQueryBatchRunner(7)
        const gone = new AbortController()
        const aborted = runQuery(SQL, gone.signal)
        const kept = runQuery(TRENDS)
        gone.abort()
        await expect(aborted).rejects.toMatchObject({ name: 'AbortError' })
        await flush()

        expect(streams[0].body.queries).toEqual([
            { target: { refId: '0', language: 'query', query: '{"kind":"TrendsQuery","series":[]}' }, time: TIME },
        ])
        answer(streams[0], 0, 1)
        await expect(kept).resolves.toEqual(totalOf(1))
    })

    it('keeps a stream open while one of its queries still waits, and stops it when none do', async () => {
        const runQuery = createQueryBatchRunner(7)
        const [first, second] = [new AbortController(), new AbortController()]
        const results = [runQuery(SQL, first.signal), runQuery(TRENDS, second.signal)]
        await flush()

        first.abort()
        expect(streams[0].signal.aborted).toBe(false)
        second.abort()
        expect(streams[0].signal.aborted).toBe(true)
        for (const result of results) {
            await expect(result).rejects.toMatchObject({ name: 'AbortError' })
        }
    })

    it('stops a stream once the query it kept open for is answered and only aborted ones remain', async () => {
        const runQuery = createQueryBatchRunner(7)
        const gone = new AbortController()
        void runQuery(SQL, gone.signal).catch(() => {})
        const kept = runQuery(TRENDS)
        await flush()

        gone.abort()
        expect(streams[0].signal.aborted).toBe(false)
        answer(streams[0], 1, 1)
        await expect(kept).resolves.toEqual(totalOf(1))
        expect(streams[0].signal.aborted).toBe(true)
    })

    it('does not ask again for an aborted query answered busy', async () => {
        const runQuery = createQueryBatchRunner(7)
        const gone = new AbortController()
        void runQuery(SQL, gone.signal).catch(() => {})
        const kept = runQuery(TRENDS)
        await flush()

        gone.abort()
        streams[0].push(`${JSON.stringify({ i: 0, error: BUSY_ERROR })}\n`)
        answer(streams[0], 1, 1)
        streams[0].close()
        await expect(kept).resolves.toEqual(totalOf(1))
        await jest.advanceTimersByTimeAsync(1000)
        expect(globalThis.fetch).toHaveBeenCalledTimes(1)
    })

    it('stops a stream once the query it still waits on aborts, after another was answered busy', async () => {
        const runQuery = createQueryBatchRunner(7)
        const retried = runQuery(SQL)
        const gone = new AbortController()
        void runQuery(TRENDS, gone.signal).catch(() => {})
        await flush()

        streams[0].push(`${JSON.stringify({ i: 0, error: BUSY_ERROR })}\n`)
        await flush()
        gone.abort()

        expect(streams[0].signal.aborted).toBe(true)
        streams[0].close()
        await jest.advanceTimersByTimeAsync(1000)
        expect(globalThis.fetch).toHaveBeenCalledTimes(2)
        answer(streams[1], 0, 1)
        await expect(retried).resolves.toEqual(totalOf(1))
    })

    it('asks once more for a query answered busy, a second after the stream ends, even when another stream is free', async () => {
        const runQuery = createQueryBatchRunner(7)
        const result = runQuery(SQL)
        await flush()
        streams[0].push(`${JSON.stringify({ i: 0, error: BUSY_ERROR })}\n`)
        streams[0].close()
        await flush()
        expect(globalThis.fetch).toHaveBeenCalledTimes(1)

        void runQuery(TRENDS).catch(() => {})
        await flush()
        expect(globalThis.fetch).toHaveBeenCalledTimes(2)
        expect(streams[1].body.queries).toHaveLength(1)
        expect(streams[1].body.queries[0].target.language).toBe('query')

        await jest.advanceTimersByTimeAsync(1000)
        expect(globalThis.fetch).toHaveBeenCalledTimes(3)
        expect(streams[2].body.queries[0].target.language).toBe('hogql')
        streams[2].push(`${JSON.stringify({ i: 0, error: BUSY_ERROR })}\n`)

        await expect(result).rejects.toThrow(BUSY_ERROR)
    })

    it('holds a busy retry until the streams open when it was answered busy have ended', async () => {
        const runQuery = createQueryBatchRunner(7)
        const first = runQuery(SQL)
        await flush()
        const second = runQuery(TRENDS)
        await flush()
        expect(globalThis.fetch).toHaveBeenCalledTimes(2)

        streams[1].push(`${JSON.stringify({ i: 0, error: BUSY_ERROR })}\n`)
        streams[1].close()
        await jest.advanceTimersByTimeAsync(5000)
        expect(globalThis.fetch).toHaveBeenCalledTimes(2)

        answer(streams[0], 0, 1)
        streams[0].close()
        await expect(first).resolves.toEqual(totalOf(1))
        await flush()
        expect(globalThis.fetch).toHaveBeenCalledTimes(3)
        expect(streams[2].body.queries[0].target.language).toBe('query')
        answer(streams[2], 0, 2)
        await expect(second).resolves.toEqual(totalOf(2))
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

    it("sends a sampled traceparent and reports the round trip under the server's trace id", async () => {
        let clock = 1000
        jest.spyOn(performance, 'now').mockImplementation(() => clock)
        const capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        traceresponse = '00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01'
        try {
            let tabOnScreen = 'main'
            const runQuery = createQueryBatchRunner(7, { context: () => ({ dashboard_tab_id: tabOnScreen }) })
            clock = 1010
            const sql = runQuery(SQL)
            const latency = runQuery(LATENCY)
            void runQuery(TRENDS).catch(() => {})
            clock = 1040
            await flush()

            const traceparent = (globalThis.fetch as jest.Mock).mock.calls[0][1].headers.traceparent
            expect(traceparent).toMatch(/^00-[0-9a-f]{32}-[0-9a-f]{16}-01$/)

            tabOnScreen = 'other'
            clock = 1100
            streams[0].push(`${JSON.stringify({ i: 0, error: 'Query timed out' })}\n`)
            await expect(sql).rejects.toThrow('Query timed out')
            clock = 1400
            streams[0].push(
                `${JSON.stringify({ i: 1, result: { frames: [], cache: { hit: true, stale: true }, provenance: { mode: 'derived', timeline: [{ source: 'engine', ms: 250.4 }] } } })}\n`
            )
            await expect(latency).resolves.toEqual({ frames: [], stale: true })
            clock = 1500
            streams[0].close()
            await flush()

            expect(capture.mock.calls.filter(([event]) => event === QUERY_BATCH_TIMING_EVENT)).toEqual([
                [
                    QUERY_BATCH_TIMING_EVENT,
                    expect.objectContaining({
                        dashboard_tab_id: 'main',
                        trace_id: '4bf92f3577b34da6a3ce929d0e0e4736',
                        batch_index: 0,
                        query_count: 3,
                        query_languages: { hogql: 1, promql: 1, query: 1 },
                        language_mix: 'hogql+promql+query',
                        status: 200,
                        failed: true,
                        error: 'No answer came back for this query',
                        aborted: false,
                        queue_wait_ms: 30,
                        headers_ms: 0,
                        first_line_ms: 60,
                        last_line_ms: 360,
                        total_ms: 460,
                        line_count: 2,
                        unanswered_queries: 1,
                        error_lines: 1,
                        cache_hits: 1,
                        stale_lines: 1,
                        derived_lines: 1,
                        engine_ms: 250,
                        since_mount_request_ms: 40,
                        since_mount_first_result_ms: 400,
                        since_mount_last_result_ms: 400,
                    }),
                ],
            ])
            expect(capture.mock.calls[0][1]?.response_bytes).toBeGreaterThan(0)
        } finally {
            jest.restoreAllMocks()
        }
    })
})
