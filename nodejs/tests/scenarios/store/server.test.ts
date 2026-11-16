import { randomUUID } from 'crypto'
import { gzipSync } from 'zlib'

import { defaultConfig } from '~/common/config/config'
import { internalFetch } from '~/common/utils/request'

import { scratchSchema } from '../environment/stack'
import { INGEST_PATH, RUNS_PATH, RunningStore, startStore } from './server'

const TOKEN = 'test-run-token'
const schema = scratchSchema(defaultConfig.DATABASE_URL, `scenario_store_${process.pid}`, [])

function scorecardOf(runId: string, overrides: Record<string, unknown> = {}): Record<string, unknown> {
    return {
        schema_version: 1,
        run_id: runId,
        card_id: 'example-card',
        card_hash: 'c0ffee',
        head_sha: 'abc1234',
        target: 'local',
        status: 'passed',
        status_reason: 'every invariant held',
        started_at: '2026-01-02T03:04:05.000Z',
        ended_at: '2026-01-02T03:09:05.000Z',
        evidence_dir: '/tmp/example/evidence',
        inv_example_passed: true,
        bars: [{ name: 'example-bar', passed: true }],
        ...overrides,
    }
}

describe('run store', () => {
    let store: RunningStore

    const ingest = (body: unknown, headers: Record<string, string> = { Authorization: `Bearer ${TOKEN}` }) =>
        internalFetch(`${store.url}${INGEST_PATH}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...headers },
            body: Buffer.isBuffer(body) ? body : JSON.stringify(body),
        })

    const read = async (path: string) => {
        const response = await internalFetch(`${store.url}${path}`)
        return { status: response.status, body: await response.json() }
    }

    beforeAll(async () => {
        await schema.create()
    })

    beforeEach(async () => {
        // Each test starts its own store on the same schema, so migrations also run on a migrated database.
        store = await startStore({ databaseUrl: schema.url, token: TOKEN, port: 0, host: '127.0.0.1' })
    })

    afterEach(async () => {
        await store.close()
    })

    afterAll(async () => {
        await schema.drop()
    })

    it('stores a run posted twice once, reads back what was posted, and keeps its series when re-sent without one', async () => {
        const runId = randomUUID()
        const series = { bucketMs: 5000, flow: [{ at: 1, offered: 3 }] }
        const topology = { nodes: ['a', 'b'], edges: [['a', 'b']] }
        const first = await ingest({ scorecard: scorecardOf(runId), series, topology, host: 'box-1' })
        expect(first.status).toBe(201)

        expect(await read(`${RUNS_PATH}/${runId}`)).toEqual({
            status: 200,
            body: expect.objectContaining({
                runId,
                cardId: 'example-card',
                status: 'passed',
                target: 'local',
                host: 'box-1',
                headSha: 'abc1234',
                cardHash: 'c0ffee',
                startedAt: '2026-01-02T03:04:05.000Z',
                endedAt: '2026-01-02T03:09:05.000Z',
                evidencePrefix: '/tmp/example/evidence',
                scorecard: scorecardOf(runId),
                series,
                topology,
            }),
        })

        const failed = scorecardOf(runId, { status: 'failed', status_reason: 'an invariant failed' })
        const again = await ingest(gzipSync(JSON.stringify({ scorecard: failed })), {
            Authorization: `Bearer ${TOKEN}`,
            'Content-Encoding': 'gzip',
        })
        expect(again.status).toBe(200)

        const { body: listed } = await read(`${RUNS_PATH}?card_id=example-card`)
        expect(listed.runs.filter((run: { runId: string }) => run.runId === runId)).toEqual([
            expect.objectContaining({ status: 'failed', host: 'box-1', scorecard: failed }),
        ])
        const { body: detail } = await read(`${RUNS_PATH}/${runId}`)
        expect(detail).toMatchObject({ status: 'failed', series, topology })
    })

    it.each([
        ['no token', {}, 401],
        ['a wrong token', { Authorization: 'Bearer not-the-token' }, 401],
        ['the token without the Bearer scheme', { Authorization: TOKEN }, 401],
        ['a scorecard without a status', { Authorization: `Bearer ${TOKEN}` }, 400],
    ])('refuses a report with %s and stores nothing', async (what, headers, status) => {
        const runId = randomUUID()
        const scorecard = scorecardOf(runId)
        if (status === 400) {
            delete scorecard.status
        }
        const response = await ingest({ scorecard }, headers)
        expect({ what, status: response.status }).toEqual({ what, status })
        expect(await read(`${RUNS_PATH}/${runId}`)).toMatchObject({ status: 404 })
    })

    it('lists runs newest first, filtered by card', async () => {
        const [older, newer, other] = [randomUUID(), randomUUID(), randomUUID()]
        await ingest({
            scorecard: scorecardOf(older, { card_id: 'list-card', started_at: '2026-02-01T00:00:00.000Z' }),
        })
        await ingest({
            scorecard: scorecardOf(newer, { card_id: 'list-card', started_at: '2026-02-02T00:00:00.000Z' }),
        })
        await ingest({ scorecard: scorecardOf(other, { card_id: 'other-card' }) })

        const { body } = await read(`${RUNS_PATH}?card_id=list-card`)
        expect(body.runs.map((run: { runId: string }) => run.runId)).toEqual([newer, older])
    })
})
