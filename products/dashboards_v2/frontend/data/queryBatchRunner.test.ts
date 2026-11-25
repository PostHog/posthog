import { ReadableStream } from 'node:stream/web'
import { TextDecoder, TextEncoder } from 'node:util'

import { NodeKind } from '~/queries/schema/schema-general'

import type { QueryRequest } from '../widgets/chart/vizTypes'
import { createQueryBatchRunner } from './queryBatchRunner'

const TIME = { from: 'now-7d', to: 'now' }
const SQL: QueryRequest = { query: { language: 'hogql', query: 'select 1 as total' }, time: TIME }
const TRENDS: QueryRequest = {
    query: { language: 'insight', query: { kind: NodeKind.TrendsQuery, series: [] } },
    time: TIME,
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

    const flush = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0))

    it('sends the queries asked in one tick as one stream and settles each as its line arrives', async () => {
        const runQuery = createQueryBatchRunner(7)
        const first = runQuery(SQL)
        const second = runQuery(TRENDS)
        await flush()

        expect(globalThis.fetch).toHaveBeenCalledTimes(1)
        expect((globalThis.fetch as jest.Mock).mock.calls[0][0]).toBe('/api/projects/7/dashboard_v2/query_batch/')
        expect((globalThis.fetch as jest.Mock).mock.calls[0][1].headers).not.toHaveProperty('Accept')
        expect(streams[0].body).toEqual({
            format: 'frames',
            queries: [
                { target: { refId: '0', language: 'hogql', query: 'select 1 as total' }, time: TIME },
                { target: { refId: '1', language: 'query', query: '{"kind":"TrendsQuery","series":[]}' }, time: TIME },
            ],
        })

        const frame = {
            name: null,
            labels: {},
            fields: [
                { name: 'day', type: 'time', unit: 'date', values: [DAY_1] },
                { name: 'total', type: 'number', values: [42] },
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
                        { name: 'total', type: 'number', values: [42] },
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

    it('asks again when the endpoint is busy with earlier batches', async () => {
        jest.useFakeTimers()
        status = 429
        const runQuery = createQueryBatchRunner(7)
        const result = runQuery(SQL)
        await jest.advanceTimersByTimeAsync(0)
        status = 200

        await jest.advanceTimersByTimeAsync(1000)
        expect(globalThis.fetch).toHaveBeenCalledTimes(2)
        streams[1].push(`${JSON.stringify({ i: 0, error: 'done' })}\n`)

        await expect(result).rejects.toThrow('done')
    })
})
