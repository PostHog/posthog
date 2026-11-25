import http from 'http'
import { AddressInfo } from 'net'

import { parseJSON } from '~/common/utils/json-parse'

import type { DevConfig } from './config'
import { QUERY_EVERY_MS, RECEIPT_ROWS, receiptTruth, unfinishedOf, workflowRuns } from './reads'

type Receipt = { runId: string; unitId: string; at: number; uuid: string }
type Seen = { method?: string; url?: string; authorization?: string; body: any }

// Answers the way the query API does: a query without a limit gets 100 rows, and a repeated query gets its
// cached answer unless the request forces a fresh one.
async function fakeDev(state: {
    receipts: Receipt[]
    series: Record<string, number[]>
    exitSeries?: Record<string, number[]>
    queryDelayMs?: number
}) {
    const seen: Seen[] = []
    const cached = new Map<string, unknown[]>()
    const server = http.createServer((req, res) => {
        let text = ''
        req.on('data', (chunk) => (text += chunk))
        req.on('end', () => {
            const body = text ? parseJSON(text) : undefined
            seen.push({ method: req.method, url: req.url, authorization: req.headers.authorization, body })
            const reply = (status: number, payload: object): void => {
                res.writeHead(status, { 'content-type': 'application/json' }).end(JSON.stringify(payload))
            }
            if (req.headers.authorization === 'Bearer phx_garbled') {
                return res.writeHead(200).end('{"detail": "phx_garbled"')
            }
            if (req.headers.authorization !== 'Bearer phx_test') {
                return reply(401, { type: 'authentication_error' })
            }
            if (req.url === '/api/projects/2/query/') {
                const key = JSON.stringify(body.query)
                const limit = Number(/limit (\d+)/.exec(body.query.query)?.[1] ?? 100)
                const scoped = /properties\.run_id\s*=\s*\{run_id\}/.test(body.query.query)
                const rows = state.receipts
                    .filter(({ runId }) => !scoped || runId === body.query.values.run_id)
                    .slice(0, limit)
                if (body.refresh === 'force_blocking' || !cached.has(key)) {
                    cached.set(
                        key,
                        rows.map(({ unitId, at, uuid }) => [unitId, at, uuid])
                    )
                }
                return void setTimeout(() => reply(200, { results: cached.get(key) }), state.queryDelayMs ?? 0)
            }
            const params = new URL(req.url!, 'http://dev').searchParams
            const names = params.get('name')!.split(',')
            const series = params.get('instance_id') === 'exit-1' ? state.exitSeries : state.series
            return reply(200, {
                labels: ['2026-11-20T14:00', '2026-11-20T15:00'],
                series: names.map((name) => ({ name, values: series?.[name] ?? [0, 0] })),
            })
        })
    })
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
    const url = `http://127.0.0.1:${(server.address() as AddressInfo).port}`
    const config: DevConfig = {
        host: url,
        offers: { teamId: 1, token: 'phc_test', workflowId: 'flow-1' },
        receiptsTeamId: 2,
        monthlyRuns: 10_000,
        key: 'phx_test',
    }
    return { config, seen, close: () => new Promise<void>((done) => server.close(() => done())) }
}

describe('dev reads', () => {
    const AT = Date.UTC(2026, 10, 20, 14, 38, 33, 636)

    it('turns the receipts of its own run into truth records, once each, querying at most every 30s and only for the judge', async () => {
        const state = {
            receipts: [{ runId: 'run-a', unitId: 'run-a-1', at: AT, uuid: 'r1' }],
            series: {},
        }
        const dev = await fakeDev(state)
        let clock = 0
        const truth = receiptTruth(dev.config, 'run-a', () => clock)
        try {
            expect(await truth.head()).toBe(1)

            state.receipts.push(
                { runId: 'run-b', unitId: 'run-b-1', at: AT, uuid: 'other-run' },
                { runId: 'run-a', unitId: 'run-a-2', at: AT + 5, uuid: 'r2' },
                { runId: 'run-a', unitId: 'run-a-2', at: AT + 5, uuid: 'r2' },
                { runId: 'run-a', unitId: 'run-a-1', at: AT + 9, uuid: 'r3' }
            )
            clock = QUERY_EVERY_MS - 1
            expect((await truth.after(1)).records).toEqual([])
            clock = QUERY_EVERY_MS
            expect(await truth.head({ timeoutMs: 500 })).toBe(1)
            const page = await truth.after(0)

            expect(page).toEqual({
                records: [
                    expect.objectContaining({ seq: 1, unitId: 'run-a-1', at: '2026-11-20T14:38:33.636Z' }),
                    expect.objectContaining({ seq: 2, unitId: 'run-a-2', actionId: 'webhook', status: 200 }),
                    expect.objectContaining({ seq: 3, unitId: 'run-a-1', kind: 'webhook' }),
                ],
                next: 3,
            })
            expect(await truth.after(2, { limit: 1 })).toEqual({ records: [page.records[2]], next: 3 })
            expect(dev.seen.filter(({ url }) => url!.endsWith('/query/'))).toHaveLength(2)
        } finally {
            await dev.close()
        }
    })

    it('waits for a forced receipts query that takes longer than the default request timeout', async () => {
        const dev = await fakeDev({
            receipts: [{ runId: 'run-a', unitId: 'run-a-1', at: AT, uuid: 'r1' }],
            series: {},
            queryDelayMs: 3_500,
        })
        try {
            expect(await receiptTruth(dev.config, 'run-a').head()).toBe(1)
        } finally {
            await dev.close()
        }
    }, 10_000)

    const receipts = (from: number, to: number): Receipt[] =>
        Array.from({ length: to - from }, (_, i) => ({
            runId: 'run-a',
            unitId: `run-a-${from + i}`,
            at: AT + from + i,
            uuid: `r${from + i}`,
        }))

    it('reads every receipt past the query API default of 100 rows, and fails when its own limit fills', async () => {
        const state = { receipts: receipts(0, 101), series: {} }
        const dev = await fakeDev(state)
        let clock = 0
        const truth = receiptTruth(dev.config, 'run-a', () => clock)
        try {
            expect(await truth.head()).toBe(101)

            state.receipts.push(...receipts(101, RECEIPT_ROWS))
            clock = QUERY_EVERY_MS
            await expect(truth.head()).rejects.toThrow(`filled all ${RECEIPT_ROWS} rows`)
        } finally {
            await dev.close()
        }
    })

    it('keeps failing a judge read between queries until a fresh receipts query succeeds', async () => {
        const state = { receipts: receipts(0, RECEIPT_ROWS), series: {} }
        const dev = await fakeDev(state)
        let clock = 0
        const truth = receiptTruth(dev.config, 'run-a', () => clock)
        try {
            await expect(truth.head()).rejects.toThrow(`filled all ${RECEIPT_ROWS} rows`)
            clock = 1
            await expect(truth.after(0)).rejects.toThrow(`filled all ${RECEIPT_ROWS} rows`)

            state.receipts.splice(RECEIPT_ROWS - 1)
            clock = QUERY_EVERY_MS
            expect(await truth.head()).toBe(RECEIPT_ROWS - 1)
            clock = QUERY_EVERY_MS + 1
            expect(await truth.head()).toBe(RECEIPT_ROWS - 1)
        } finally {
            await dev.close()
        }
    })

    it.each([
        ['refuses', 'phx_revoked', 'dev answered the receipts query with 401'],
        [
            'answers with a body that is not JSON',
            'phx_garbled',
            'dev answered the receipts query with a body that is not JSON',
        ],
    ])('fails a truth read dev %s, and leaves the body out of the error', async (_how, key, message) => {
        const dev = await fakeDev({ receipts: [], series: {} })
        try {
            const read = receiptTruth({ ...dev.config, key }, 'run-a').head()
            await expect(read).rejects.toThrow(new Error(message))
        } finally {
            await dev.close()
        }
    })

    it.each<[string, number[]]>([
        ['a count it cannot add up', ['unknown' as unknown as number, 3]],
        ['no buckets at all', []],
    ])('fails a workflow metrics read that answers %s, rather than reading it as zero', async (_how, values) => {
        const dev = await fakeDev({ receipts: [], series: { triggered: values } })
        try {
            await expect(workflowRuns(dev.config, '2026-11-20T14:00:00.000Z', 'hour')).rejects.toThrow(
                'dev answered the workflow metrics read without a count of triggered'
            )
        } finally {
            await dev.close()
        }
    })

    it('counts the triggered workflow runs that have not reached its exit, apart from the runs quota limited before any trigger', async () => {
        const dev = await fakeDev({
            receipts: [],
            series: { triggered: [3, 7], fetch: [5, 9], failed: [0, 1], quota_limited: [0, 1], succeeded: [9, 18] },
            exitSeries: { succeeded: [2, 4] },
        })
        try {
            const runs = await workflowRuns(dev.config, '2026-11-20T14:00:00.000Z', 'hour', 'exit-1')

            expect([runs, unfinishedOf(runs)]).toEqual([{ triggered: 10, exited: 6, quota_limited: 1 }, 4])
        } finally {
            await dev.close()
        }
    })
})
