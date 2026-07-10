import type { S3Client } from '@aws-sdk/client-s3'
import { createHash, randomUUID } from 'node:crypto'
import { Pool } from 'pg'
import request from 'supertest'

/**
 * Deterministic uuid from a short label. PG enforces uuid format on
 * `agent_session.{id,application_id,revision_id}` etc; tests previously used
 * label-shaped strings like `'s-a'` / `'app-1'`. Hashing keeps the labels in
 * the source for readability and produces a stable mapping for assertions.
 */
function uuidFor(label: string): string {
    const h = createHash('md5').update(label).digest('hex')
    return `${h.slice(0, 8)}-${h.slice(8, 12)}-4${h.slice(13, 16)}-8${h.slice(17, 20)}-${h.slice(20, 32)}`
}

import {
    AgentSession,
    AgentSpecSchema,
    buildTestBundleStore,
    type CatalogModel,
    EMPTY_USAGE_TOTAL,
    INTERNAL_JWT_AUDIENCE,
    mintInternalJwt,
    newTestPrefix,
    PgRevisionStore,
    PgSessionQueue,
    S3BundleStore,
    wipeTestPrefix,
} from '@posthog/agent-shared'
import { reset } from '@posthog/agent-shared/testing'

import { buildJanitorApp } from './server'

const TEST_DB_URL =
    process.env.AGENT_TEST_DB_URL ?? 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue_test'

let pool: Pool
let bundlePrefix: string
let bundleClient: S3Client
let bundleStore: S3BundleStore

beforeAll(() => {
    pool = new Pool({ connectionString: TEST_DB_URL })
})

afterAll(async () => {
    await pool.end()
})

beforeEach(async () => {
    await reset({ databaseUrl: TEST_DB_URL })
    bundlePrefix = newTestPrefix('agent_bundles_janitor_srv_test')
    const built = buildTestBundleStore(bundlePrefix)
    bundleClient = built.client
    bundleStore = built.store
})

afterEach(async () => {
    if (bundleClient) {
        await wipeTestPrefix(bundleClient, bundlePrefix).catch(() => undefined)
        bundleClient.destroy()
    }
})

function session(label: string): AgentSession {
    return {
        id: uuidFor(label),
        application_id: uuidFor('app'),
        revision_id: uuidFor('rev'),
        team_id: 1,
        external_key: null,
        idempotency_key: null,
        trigger_metadata: null,
        state: 'running',
        conversation: [{ role: 'user', content: 'hi', timestamp: Date.now() }],
        pending_inputs: [],
        principal: null,
        retry_count: 0,
        usage_total: { ...EMPTY_USAGE_TOTAL },
        acl: [],
        pending_elevation_requests: [],
        created_at: '2026-05-27',
        updated_at: '2026-05-27',
    }
}

describe('janitor HTTP', () => {
    function mk(): { queue: PgSessionQueue; app: ReturnType<typeof buildJanitorApp> } {
        const queue = new PgSessionQueue(pool)
        const app = buildJanitorApp({
            queue,
            sweep: { queue, stuckRunningThresholdMs: 60_000 },
        })
        return { queue, app }
    }

    it('GET /healthz returns ok', async () => {
        const { app } = mk()
        const res = await request(app).get('/healthz')
        expect(res.status).toBe(200)
    })

    it('GET /models returns per-Mtok pricing + levels resolved to canonical ids', async () => {
        // haiku is dated-only with a dashed undated alias — the form the level
        // list uses; resolution must map it to the catalog canonical.
        const catalog: CatalogModel[] = [
            {
                canonical: 'anthropic/claude-haiku-4.5',
                id: 'claude-haiku-4-5-20251001',
                owned_by: 'anthropic',
                context_window: 200_000,
                aliases: ['claude-haiku-4-5'],
                pricing: { prompt: 0.000001, completion: 0.000005, cache_read: 0.0000001 },
            },
            {
                canonical: 'openai/gpt-5-mini',
                id: 'gpt-5-mini',
                owned_by: 'openai',
                context_window: 400_000,
                aliases: [],
                pricing: { prompt: 0.00000025, completion: 0.000002 },
            },
            {
                canonical: 'anthropic/claude-opus-4.7',
                id: 'claude-opus-4-7',
                owned_by: 'anthropic',
                context_window: 1_000_000,
                aliases: [],
                pricing: { prompt: 0.000005, completion: 0.000025 },
            },
            {
                canonical: 'openai/gpt-5-pro',
                id: 'gpt-5-pro',
                owned_by: 'openai',
                context_window: 400_000,
                aliases: [],
                pricing: { prompt: 0.000015, completion: 0.00012 },
            },
        ]
        const queue = new PgSessionQueue(pool)
        const app = buildJanitorApp({
            queue,
            sweep: { queue, stuckRunningThresholdMs: 60_000 },
            gatewayCatalog: { list: async () => catalog },
        })

        const res = await request(app).get('/models')
        expect(res.status).toBe(200)
        const haiku = (res.body.models as Array<Record<string, unknown>>).find(
            (m) => m.model === 'anthropic/claude-haiku-4.5'
        )
        // Per-token USD → per-Mtok; cache omitted when the model has none.
        expect(haiku).toMatchObject({
            provider: 'anthropic',
            context_window: 200_000,
            input: 1,
            output: 5,
            cache_read: 0.1,
        })
        expect(haiku).not.toHaveProperty('cache_write')
        // Levels resolve the dashed-alias level entries to catalog canonicals.
        expect(res.body.levels.low).toEqual(['anthropic/claude-haiku-4.5', 'openai/gpt-5-mini'])
        expect(res.body.levels.high).toEqual(['anthropic/claude-opus-4.7', 'openai/gpt-5-pro'])
    })

    it('GET /models fails open with an empty catalog when no gateway is wired', async () => {
        const { app } = mk()
        const res = await request(app).get('/models')
        expect(res.status).toBe(200)
        expect(res.body.models).toEqual([])
        expect(Object.keys(res.body.levels)).toEqual(['low', 'medium', 'high'])
    })

    it('GET /spec-schema returns the full inlined agent-spec JSON Schema with descriptions', async () => {
        const { app } = mk()
        const res = await request(app).get('/spec-schema')
        expect(res.status).toBe(200)
        expect(res.body.section).toBeNull()
        const schema = res.body.spec_json_schema
        // Inlined (no $defs) so every slice is self-contained.
        expect(schema.$defs).toBeUndefined()
        expect(Object.keys(schema.properties)).toContain('models')
        // Descriptions travel with the schema — the whole point of the tool.
        expect(typeof schema.properties.models.description).toBe('string')
    })

    it('GET /spec-schema?section=models returns just the models slice', async () => {
        const { app } = mk()
        const res = await request(app).get('/spec-schema').query({ section: 'models' })
        expect(res.status).toBe(200)
        expect(res.body.section).toBe('models')
        expect(res.body.spec_json_schema.$schema).toBeTruthy()
        expect(res.body.spec_json_schema.oneOf).toHaveLength(2) // auto | manual
    })

    it('GET /spec-schema?section=bogus is a 400 listing the valid sections', async () => {
        const { app } = mk()
        const res = await request(app).get('/spec-schema').query({ section: 'bogus' })
        expect(res.status).toBe(400)
        expect(res.body.error).toBe('unknown_section')
        expect(res.body.sections).toContain('models')
    })

    it('GET /sessions?application_id= returns summaries, most recently active first', async () => {
        const { queue, app } = mk()
        // s-a was created first but touched most recently — activity ordering
        // must put it ahead of the newer-created s-b.
        const a = {
            ...session('s-a'),
            application_id: uuidFor('app-1'),
            created_at: '2026-05-01T00:00:00Z',
            updated_at: '2026-05-04T00:00:00Z',
        }
        const b = {
            ...session('s-b'),
            application_id: uuidFor('app-1'),
            created_at: '2026-05-02T00:00:00Z',
            updated_at: '2026-05-02T00:00:00Z',
        }
        const c = { ...session('s-c'), application_id: uuidFor('other'), created_at: '2026-05-03T00:00:00Z' }
        await queue.enqueue(a)
        await queue.enqueue(b)
        await queue.enqueue(c)
        const res = await request(app)
            .get('/sessions')
            .query({ application_id: uuidFor('app-1') })
        expect(res.status).toBe(200)
        const ids = (res.body.results as Array<{ id: string }>).map((s) => s.id)
        expect(ids).toEqual([uuidFor('s-a'), uuidFor('s-b')])
        expect(res.body.count).toBe(2)
        // Summaries strip the heavy conversation body.
        expect(Object.keys(res.body.results[0])).not.toContain('conversation')
        expect(res.body.results[0]).toMatchObject({ turns: 1, state: 'running' })
    })

    it('GET /sessions without application_id returns a structured 400', async () => {
        const { app } = mk()
        const res = await request(app).get('/sessions')
        expect(res.status).toBe(400)
        expect(res.body.error).toBe('invalid_request')
        // The zod issues array points at the offending field so callers can
        // surface useful messages instead of a generic "bad request".
        const issues = res.body.issues as Array<{ path: string[]; message: string }>
        expect(issues.some((i) => i.path[0] === 'application_id')).toBe(true)
    })

    it('GET /sessions with garbage state value returns 400 instead of crashing', async () => {
        // Pre-zod, an unknown state silently passed through to the queue layer
        // and could cause weird filter behavior. The schema rejects it now.
        const { app } = mk()
        const res = await request(app)
            .get('/sessions')
            .query({ application_id: uuidFor('app-1'), state: 'banana' })
        expect(res.status).toBe(400)
        expect(res.body.error).toBe('invalid_request')
    })

    // Legacy file/bundle size-cap tests removed alongside the typed bundle
    // rollout. Per-resource limits live in the typed body schemas now
    // (`TypedSkillSchema.body.max`, `TypedToolSchema.source.max`); covered
    // by the typed-bundle-authoring e2e suite.

    it('GET /sessions supports state / revision_id / created_after filters', async () => {
        const { queue, app } = mk()
        await queue.enqueue({
            ...session('done-r1'),
            application_id: uuidFor('app-1'),
            revision_id: uuidFor('rev-1'),
            state: 'completed',
            created_at: '2026-05-02T00:00:00Z',
        })
        await queue.enqueue({
            ...session('fail-r1'),
            application_id: uuidFor('app-1'),
            revision_id: uuidFor('rev-1'),
            state: 'failed',
            created_at: '2026-05-03T00:00:00Z',
        })
        await queue.enqueue({
            ...session('done-r2'),
            application_id: uuidFor('app-1'),
            revision_id: uuidFor('rev-2'),
            state: 'completed',
            created_at: '2026-04-25T00:00:00Z',
        })
        // state=completed,failed → both completed and failed across revs
        const both = await request(app)
            .get('/sessions')
            .query({ application_id: uuidFor('app-1'), state: 'completed,failed' })
        expect((both.body.results as Array<{ id: string }>).map((s) => s.id).sort()).toEqual(
            [uuidFor('done-r1'), uuidFor('done-r2'), uuidFor('fail-r1')].sort()
        )
        // revision_id filter scopes to one revision
        const r1 = await request(app)
            .get('/sessions')
            .query({ application_id: uuidFor('app-1'), revision_id: uuidFor('rev-1') })
        expect((r1.body.results as Array<{ id: string }>).map((s) => s.id).sort()).toEqual(
            [uuidFor('done-r1'), uuidFor('fail-r1')].sort()
        )
        // created_after excludes older sessions
        const recent = await request(app)
            .get('/sessions')
            .query({ application_id: uuidFor('app-1'), created_after: '2026-05-01T00:00:00Z' })
        expect((recent.body.results as Array<{ id: string }>).map((s) => s.id).sort()).toEqual(
            [uuidFor('done-r1'), uuidFor('fail-r1')].sort()
        )
    })

    it('GET /sessions?search matches transcript text, external_key and id', async () => {
        const { queue, app } = mk()
        await queue.enqueue({
            ...session('s-deploy'),
            application_id: uuidFor('app-1'),
            external_key: 'slack:C123',
            conversation: [
                { role: 'user', content: 'can you deploy the WIDGET service?', timestamp: 1 },
                {
                    role: 'assistant',
                    content: [{ type: 'text', text: 'Deploying now.' }],
                    api: 'a',
                    provider: 'a',
                    model: 'm',
                    usage: { input: 1, output: 1, cost: { input: 0, output: 0, total: 0 } },
                    timestamp: 2,
                },
            ],
        })
        await queue.enqueue({
            ...session('s-unrelated'),
            application_id: uuidFor('app-1'),
            external_key: 'slack:C999',
            conversation: [{ role: 'user', content: 'what is the weather', timestamp: 1 }],
        })
        // Transcript-text match via the persisted search_text digest, case-insensitive.
        const byText = await request(app)
            .get('/sessions')
            .query({ application_id: uuidFor('app-1'), search: 'widget' })
        expect((byText.body.results as Array<{ id: string }>).map((s) => s.id)).toEqual([uuidFor('s-deploy')])
        expect(byText.body.count).toBe(1)
        // external_key match.
        const byKey = await request(app)
            .get('/sessions')
            .query({ application_id: uuidFor('app-1'), search: 'C999' })
        expect((byKey.body.results as Array<{ id: string }>).map((s) => s.id)).toEqual([uuidFor('s-unrelated')])
        // id match.
        const byId = await request(app)
            .get('/sessions')
            .query({ application_id: uuidFor('app-1'), search: uuidFor('s-deploy') })
        expect((byId.body.results as Array<{ id: string }>).map((s) => s.id)).toEqual([uuidFor('s-deploy')])
        // No match → empty, not an error.
        const none = await request(app)
            .get('/sessions')
            .query({ application_id: uuidFor('app-1'), search: 'zzz-nope' })
        expect(none.body.results).toHaveLength(0)
        expect(none.body.count).toBe(0)
    })

    it('GET /sessions?search treats LIKE metacharacters literally', async () => {
        const { queue, app } = mk()
        await queue.enqueue({ ...session('s-pct'), application_id: uuidFor('app-1'), external_key: 'batch-50%-run' })
        await queue.enqueue({ ...session('s-plain'), application_id: uuidFor('app-1'), external_key: 'batch-50-run' })
        const res = await request(app)
            .get('/sessions')
            .query({ application_id: uuidFor('app-1'), search: '50%' })
        expect((res.body.results as Array<{ id: string }>).map((s) => s.id)).toEqual([uuidFor('s-pct')])
    })

    it('GET /sessions summaries derive preview from search_text + usage_total off the persisted columns', async () => {
        const { queue, app } = mk()
        await queue.enqueue({
            ...session('s-rich'),
            application_id: uuidFor('app-1'),
            // The runner accumulates this; we set it explicitly so the summary
            // matches what a live row would carry.
            usage_total: {
                ...EMPTY_USAGE_TOTAL,
                tokens_in: 50,
                tokens_out: 10,
                cost_input: 0.0005,
                cost_output: 0.0002,
                cost_total: 0.0007,
            },
            conversation: [
                { role: 'user', content: 'hi', timestamp: 1 },
                {
                    role: 'assistant',
                    content: [{ type: 'text', text: 'hello back!' }],
                    api: 'anthropic-messages',
                    provider: 'anthropic',
                    model: 'anthropic/claude-haiku-4-5',
                    usage: { input: 50, output: 10, cost: { input: 0.0005, output: 0.0002, total: 0.0007 } },
                    timestamp: 2,
                },
            ],
        })
        const res = await request(app)
            .get('/sessions')
            .query({ application_id: uuidFor('app-1') })
        // Preview is the conversation digest (user + assistant text), not just
        // the last assistant line — it comes off the persisted search_text.
        expect(res.body.results[0].preview).toBe('hi hello back!')
        expect(res.body.results[0].usage_total).toMatchObject({
            tokens_in: 50,
            tokens_out: 10,
            cost_total: 0.0007,
        })
    })

    it('GET /sessions/:id returns session, 404 if missing', async () => {
        const { queue, app } = mk()
        await queue.enqueue(session('s1'))
        const ok = await request(app).get(`/sessions/${uuidFor('s1')}`)
        expect(ok.status).toBe(200)
        expect(ok.body.id).toBe(uuidFor('s1'))
        expect(ok.body.conversation_trimmed).toBe(false)
        expect(ok.body.usage_total).not.toBeUndefined()
        const miss = await request(app).get(`/sessions/${uuidFor('nope')}`)
        expect(miss.status).toBe(404)
    })

    it('GET /sessions/:id?last_n trims the transcript but keeps usage_total accurate', async () => {
        const { queue, app } = mk()
        await queue.enqueue({
            ...session('s-long'),
            // Mirror what the runner would have accumulated by turn 2.
            usage_total: {
                ...EMPTY_USAGE_TOTAL,
                tokens_in: 30,
                tokens_out: 15,
                cost_input: 0.0003,
                cost_output: 0.00015,
                cost_total: 0.00045,
            },
            conversation: [
                { role: 'user', content: 'turn1', timestamp: 1 },
                {
                    role: 'assistant',
                    content: [{ type: 'text', text: 'reply1' }],
                    api: 'a',
                    provider: 'a',
                    model: 'm',
                    usage: { input: 10, output: 5, cost: { input: 0.0001, output: 0.00005, total: 0.00015 } },
                    timestamp: 2,
                },
                { role: 'user', content: 'turn2', timestamp: 3 },
                {
                    role: 'assistant',
                    content: [{ type: 'text', text: 'reply2' }],
                    api: 'a',
                    provider: 'a',
                    model: 'm',
                    usage: { input: 20, output: 10, cost: { input: 0.0002, output: 0.0001, total: 0.0003 } },
                    timestamp: 4,
                },
            ],
        })
        const res = await request(app)
            .get(`/sessions/${uuidFor('s-long')}`)
            .query({ last_n: 2 })
        expect(res.body.conversation_trimmed).toBe(true)
        expect(res.body.conversation_total_turns).toBe(4)
        expect(res.body.conversation).toHaveLength(2)
        // Last two messages are turn2 + reply2.
        expect(res.body.conversation[0].content).toBe('turn2')
        // usage_total comes off the persisted column — not derived from the trim.
        expect(res.body.usage_total.tokens_in).toBe(30)
    })

    it('POST /sessions/backfill_usage rewrites usage_total from conversation', async () => {
        const { queue, app } = mk()
        await queue.enqueue({
            ...session('s-backfill'),
            application_id: uuidFor('app-x'),
            conversation: [
                { role: 'user', content: 'q', timestamp: 1 },
                {
                    role: 'assistant',
                    content: [{ type: 'text', text: 'a' }],
                    api: 'a',
                    provider: 'a',
                    model: 'm',
                    usage: { input: 7, output: 3, cost: { input: 0.01, output: 0.005, total: 0.015 } },
                    timestamp: 2,
                },
            ],
        })
        // Dry-run reports the would-be change but doesn't persist.
        const dry = await request(app)
            .post('/sessions/backfill_usage')
            .send({ application_id: uuidFor('app-x'), dry_run: true })
        expect(dry.status).toBe(200)
        expect(dry.body).toMatchObject({ scanned: 1, updated: 1, dry_run: true })
        expect((await queue.get(uuidFor('s-backfill')))!.usage_total.tokens_in).toBe(0)

        // Real run writes the recomputed totals.
        const real = await request(app)
            .post('/sessions/backfill_usage')
            .send({ application_id: uuidFor('app-x'), dry_run: false })
        expect(real.body).toMatchObject({ scanned: 1, updated: 1, dry_run: false })
        const after = (await queue.get(uuidFor('s-backfill')))!
        expect(after.usage_total.tokens_in).toBe(7)
        // Cost is owned by the gateway's settled figure, never recomputed from pi-ai's
        // conversation estimates — so the backfill rewrites tokens but leaves cost at zero.
        expect(after.usage_total.cost_total).toBe(0)

        // Second run finds nothing to update.
        const repeat = await request(app)
            .post('/sessions/backfill_usage')
            .send({ application_id: uuidFor('app-x'), dry_run: false })
        expect(repeat.body).toMatchObject({ scanned: 1, updated: 0 })
    })

    it('POST /sessions/:id/cancel marks cancelled', async () => {
        const { queue, app } = mk()
        await queue.enqueue(session('s2'))
        const res = await request(app).post(`/sessions/${uuidFor('s2')}/cancel`)
        expect(res.status).toBe(200)
        expect(res.body).toMatchObject({ ok: true, state: 'cancelled' })
        expect((await queue.get(uuidFor('s2')))!.state).toBe('cancelled')
    })

    it('POST /sessions/:id/cancel is idempotent on terminal state', async () => {
        const { queue, app } = mk()
        await queue.enqueue(session('s2b'))
        await request(app).post(`/sessions/${uuidFor('s2b')}/cancel`)
        const second = await request(app).post(`/sessions/${uuidFor('s2b')}/cancel`)
        expect(second.status).toBe(200)
        expect(second.body).toMatchObject({ ok: true, idempotent: true, state: 'cancelled' })
    })

    /* ────────────────────────── fleet stats ────────────────────────── */

    it('GET /sessions/stats rolls up per-application counts + spend', async () => {
        const { queue, app } = mk()
        const now = Date.now()
        const iso = (d: number): string => new Date(d).toISOString()
        const recent = iso(now - 60_000)
        const old = iso(now - 7 * 24 * 60 * 60 * 1000)
        await queue.enqueue({
            ...session('live-1'),
            application_id: uuidFor('app-x'),
            state: 'running',
            created_at: recent,
            updated_at: recent,
            usage_total: { ...EMPTY_USAGE_TOTAL, cost_total: 0.5 },
        })
        await queue.enqueue({
            ...session('done-1'),
            application_id: uuidFor('app-x'),
            state: 'completed',
            created_at: recent,
            updated_at: recent,
            usage_total: { ...EMPTY_USAGE_TOTAL, cost_total: 1.25 },
        })
        await queue.enqueue({
            ...session('failed-1'),
            application_id: uuidFor('app-x'),
            state: 'failed',
            created_at: recent,
            updated_at: recent,
            usage_total: { ...EMPTY_USAGE_TOTAL, cost_total: 0.1 },
        })
        await queue.enqueue({
            ...session('old-1'),
            application_id: uuidFor('app-x'),
            state: 'completed',
            created_at: old,
            updated_at: old,
            usage_total: { ...EMPTY_USAGE_TOTAL, cost_total: 99 },
        })
        await queue.enqueue({
            ...session('other-app'),
            application_id: uuidFor('app-y'),
            state: 'running',
            created_at: recent,
            updated_at: recent,
            usage_total: { ...EMPTY_USAGE_TOTAL, cost_total: 99 },
        })
        const res = await request(app)
            .get('/sessions/stats')
            .query({ application_id: uuidFor('app-x') })
        expect(res.status).toBe(200)
        expect(res.body).toMatchObject({
            liveCount: 1,
            sessionsInWindowCount: 3,
            spendInWindowUsd: 0.5 + 1.25 + 0.1,
            failedInWindowCount: 1,
        })
        expect(res.body.lastActivityAt).toBe(recent)
    })

    it('GET /fleet/stats rolls up per-team counts + spend', async () => {
        const { queue, app } = mk()
        const now = Date.now()
        const recent = new Date(now - 60_000).toISOString()
        await queue.enqueue({
            ...session('t1-live'),
            team_id: 7,
            state: 'running',
            created_at: recent,
            updated_at: recent,
            usage_total: { ...EMPTY_USAGE_TOTAL, cost_total: 2 },
        })
        await queue.enqueue({
            ...session('t1-done'),
            team_id: 7,
            state: 'completed',
            created_at: recent,
            updated_at: recent,
            usage_total: { ...EMPTY_USAGE_TOTAL, cost_total: 1 },
        })
        await queue.enqueue({
            ...session('t2-other'),
            team_id: 99,
            state: 'running',
            created_at: recent,
            updated_at: recent,
            usage_total: { ...EMPTY_USAGE_TOTAL, cost_total: 50 },
        })
        const res = await request(app).get('/fleet/stats').query({ team_id: 7 })
        expect(res.status).toBe(200)
        expect(res.body).toMatchObject({ liveCount: 1, sessionsInWindowCount: 2, spendInWindowUsd: 3 })
    })

    it('GET /sessions/live returns live sessions for a team', async () => {
        const { queue, app } = mk()
        const now = Date.now()
        const recent = new Date(now - 60_000).toISOString()
        const newer = new Date(now - 30_000).toISOString()
        await queue.enqueue({
            ...session('live-old'),
            team_id: 7,
            state: 'queued',
            created_at: recent,
            updated_at: recent,
        })
        await queue.enqueue({
            ...session('live-new'),
            team_id: 7,
            state: 'running',
            created_at: newer,
            updated_at: newer,
        })
        await queue.enqueue({
            ...session('done'),
            team_id: 7,
            state: 'completed',
            created_at: newer,
            updated_at: newer,
        })
        await queue.enqueue({
            ...session('other-team'),
            team_id: 99,
            state: 'running',
            created_at: newer,
            updated_at: newer,
        })
        const res = await request(app).get('/sessions/live').query({ team_id: 7 })
        expect(res.status).toBe(200)
        const ids = (res.body.results as Array<{ id: string }>).map((s) => s.id)
        expect(ids).toEqual([uuidFor('live-new'), uuidFor('live-old')])
        expect(Object.keys(res.body.results[0])).not.toContain('conversation')
    })

    it('GET /sessions/stats without application_id returns 400', async () => {
        const { app } = mk()
        const res = await request(app).get('/sessions/stats')
        expect(res.status).toBe(400)
        expect(res.body.error).toBe('invalid_request')
    })

    it('GET /fleet/stats without team_id returns 400', async () => {
        const { app } = mk()
        const res = await request(app).get('/fleet/stats')
        expect(res.status).toBe(400)
        expect(res.body.error).toBe('invalid_request')
    })

    it('POST /sweep returns counts', async () => {
        const { app } = mk()
        const res = await request(app).post('/sweep')
        expect(res.status).toBe(200)
        expect(res.body).toEqual({
            requeued: 0,
            poisoned: 0,
            closed: 0,
            expired_approvals: 0,
            cleared_idempotency_keys: 0,
            reaped_sandboxes: 0,
            sandbox_reap_failures: 0,
        })
    })

    it('enforces aud-bound JWT auth when an internal signing key is configured', async () => {
        const queue = new PgSessionQueue(pool)
        const signingKey = 'topsecret'
        const app = buildJanitorApp({
            queue,
            sweep: { queue, stuckRunningThresholdMs: 60_000 },
            internalSigningKey: signingKey,
        })

        const noAuth = await request(app).get('/sessions/00000000-0000-4000-8000-00000000ddff')
        expect(noAuth.status).toBe(401)
        expect(noAuth.body).toMatchObject({ reason: 'missing_token' })

        const rawSecret = await request(app)
            .get('/sessions/00000000-0000-4000-8000-00000000ddff')
            .set('x-internal-secret', 'topsecret')
        expect(rawSecret.status).toBe(401)

        // Token minted for a different audience must be rejected.
        const wrongAud = await mintInternalJwt({
            audience: INTERNAL_JWT_AUDIENCE.INGRESS_PREVIEW,
            signingKey,
        })
        const wrongAudRes = await request(app)
            .get('/sessions/00000000-0000-4000-8000-00000000ddff')
            .set('x-internal-secret', wrongAud)
        expect(wrongAudRes.status).toBe(401)

        // Right audience, wrong signing key.
        const wrongKey = await mintInternalJwt({
            audience: INTERNAL_JWT_AUDIENCE.JANITOR_RPC,
            signingKey: 'other-key',
        })
        const wrongKeyRes = await request(app)
            .get('/sessions/00000000-0000-4000-8000-00000000ddff')
            .set('x-internal-secret', wrongKey)
        expect(wrongKeyRes.status).toBe(401)

        const ok = await mintInternalJwt({
            audience: INTERNAL_JWT_AUDIENCE.JANITOR_RPC,
            signingKey,
        })
        const withAuth = await request(app)
            .get('/sessions/00000000-0000-4000-8000-00000000ddff')
            .set('x-internal-secret', ok)
        expect(withAuth.status).toBe(404) // session not found, but auth passed
    })

    /* ────────────────────────── catalog ────────────────────────── */

    it('GET /native_tools returns the registry catalog', async () => {
        const { app } = mk()
        const res = await request(app).get('/native_tools')
        expect(res.status).toBe(200)
        const ids = (res.body.tools as Array<{ id: string }>).map((t) => t.id)
        // Spot-check a couple of stable tools from different families. Meta
        // tools (`@posthog/meta-*`) are auto-included by the runner outside
        // ALL_TOOLS and are deliberately NOT in this list.
        expect(ids).toEqual(expect.arrayContaining(['@posthog/query', '@posthog/memory-list']))
    })

    /* ────────────────────────── revisions ────────────────────────── */

    async function mkRevisionApp(): Promise<{
        revisions: PgRevisionStore
        bundles: S3BundleStore
        app: ReturnType<typeof buildJanitorApp>
        revisionId: string
    }> {
        const revisions = new PgRevisionStore(pool)
        const bundles = bundleStore
        const queue = new PgSessionQueue(pool)
        const apprec = await revisions.createApplication({ team_id: 1, slug: 'a', name: 'A', description: '' })
        const rev = await revisions.createRevision({
            application_id: apprec.id,
            parent_revision_id: null,
            created_by_id: null,
            bundle_uri: 'mem://b',
            spec: AgentSpecSchema.parse({
                models: { mode: 'manual', models: [{ model: 'test/x' }] },
                triggers: [
                    {
                        type: 'chat',
                        config: {},
                        auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] },
                    },
                ],
            }),
        })
        const app = buildJanitorApp({
            queue,
            sweep: { queue, stuckRunningThresholdMs: 60_000 },
            revisions,
            bundles,
        })
        return { revisions, bundles, app, revisionId: rev.id }
    }

    it('GET /revisions/:id/system-prompt returns the assembled prompt + framework version', async () => {
        const { app, bundles, revisionId } = await mkRevisionApp()
        await bundles.write(revisionId, 'agent.md', '## Author content\n\nThis is the author-side prompt.')
        const res = await request(app).get(`/revisions/${revisionId}/system-prompt`)
        expect(res.status).toBe(200)
        expect(res.body.revision_id).toBe(revisionId)
        expect(res.body.framework_prompt_version).toBeGreaterThanOrEqual(1)
        const prompt = res.body.system_prompt as string
        // Framework preamble landed first…
        expect(prompt).toContain('Platform guidance')
        expect(prompt).toContain('@posthog/meta-end-turn')
        // …then the author content.
        expect(prompt).toContain('This is the author-side prompt.')
        expect(prompt.indexOf('Platform guidance')).toBeLessThan(prompt.indexOf('This is the author-side prompt.'))
    })

    it('GET /revisions/:id/system-prompt 404s for an unknown revision', async () => {
        const { app } = await mkRevisionApp()
        const res = await request(app).get('/revisions/00000000-0000-0000-0000-000000000000/system-prompt')
        expect(res.status).toBe(404)
    })

    it('POST /revisions/:id/cron/fire enqueues a session for the named cron', async () => {
        const revisions = new PgRevisionStore(pool)
        const bundles = bundleStore
        const queue = new PgSessionQueue(pool)
        const apprec = await revisions.createApplication({ team_id: 1, slug: 'a', name: 'A', description: '' })
        const rev = await revisions.createRevision({
            application_id: apprec.id,
            parent_revision_id: null,
            created_by_id: null,
            bundle_uri: 'mem://b',
            spec: AgentSpecSchema.parse({
                models: { mode: 'manual', models: [{ model: 'test/x' }] },
                triggers: [
                    {
                        type: 'cron',
                        config: { name: 'digest', schedule: '0 9 * * MON', prompt: 'Run the digest.' },
                    },
                ],
            }),
        })
        const app = buildJanitorApp({
            queue,
            sweep: { queue, stuckRunningThresholdMs: 60_000 },
            revisions,
            bundles,
        })
        const res = await request(app)
            .post(`/revisions/${rev.id}/cron/fire`)
            .send({ cron_name: 'digest', request_id: 'click-1' })
        expect(res.status).toBe(200)
        expect(res.body.ok).toBe(true)
        expect(res.body.session_id).toBeTruthy()
        expect(res.body.idempotency_key).toBe(`cron-manual:${rev.id}:digest:click-1`)
        const session = await queue.get(res.body.session_id)
        expect((session!.conversation[0] as { content: string }).content).toBe('Run the digest.')
    })

    it('POST /revisions/:id/cron/fire dedupes repeat clicks with the same request_id', async () => {
        const revisions = new PgRevisionStore(pool)
        const bundles = bundleStore
        const queue = new PgSessionQueue(pool)
        const apprec = await revisions.createApplication({ team_id: 1, slug: 'a', name: 'A', description: '' })
        const rev = await revisions.createRevision({
            application_id: apprec.id,
            parent_revision_id: null,
            created_by_id: null,
            bundle_uri: 'mem://b',
            spec: AgentSpecSchema.parse({
                models: { mode: 'manual', models: [{ model: 'test/x' }] },
                triggers: [
                    {
                        type: 'cron',
                        config: { name: 'digest', schedule: '0 9 * * MON', prompt: 'p' },
                    },
                ],
            }),
        })
        const app = buildJanitorApp({
            queue,
            sweep: { queue, stuckRunningThresholdMs: 60_000 },
            revisions,
            bundles,
        })
        const a = await request(app)
            .post(`/revisions/${rev.id}/cron/fire`)
            .send({ cron_name: 'digest', request_id: 'click-1' })
        const b = await request(app)
            .post(`/revisions/${rev.id}/cron/fire`)
            .send({ cron_name: 'digest', request_id: 'click-1' })
        expect(a.body.session_id).toBe(b.body.session_id)
    })

    it('POST /revisions/:id/cron/fire 404s when the cron name is not declared', async () => {
        const { app, revisionId } = await mkRevisionApp()
        const res = await request(app)
            .post(`/revisions/${revisionId}/cron/fire`)
            .send({ cron_name: 'ghost', request_id: 'r' })
        expect(res.status).toBe(404)
        expect(res.body.error).toBe('unknown_cron')
    })

    it('GET /revisions/:id/manifest returns the file list + state', async () => {
        const { app, bundles, revisionId } = await mkRevisionApp()
        await bundles.write(revisionId, 'agent.md', 'hello')
        await bundles.write(revisionId, 'skills/research.md', 'be thorough')
        const res = await request(app).get(`/revisions/${revisionId}/manifest`)
        expect(res.status).toBe(200)
        expect(res.body.state).toBe('draft')
        const paths = (res.body.files as Array<{ path: string }>).map((f) => f.path).sort()
        expect(paths).toEqual(['agent.md', 'skills/research.md'])
    })

    it('PUT /revisions/:id/skills/:id writes SKILL.md + companion files', async () => {
        const { app, bundles, revisionId } = await mkRevisionApp()
        const res = await request(app)
            .put(`/revisions/${revisionId}/skills/triage`)
            .send({
                description: 'triage inbound',
                body: '---\nname: triage\n---\nthe body',
                files: [{ path: 'references/api.md', content: '# API' }],
            })
        expect(res.status).toBe(200)
        expect(res.body).toMatchObject({ ok: true, skill_id: 'triage', files_written: 1 })
        expect(await bundles.readText(revisionId, 'skills/triage/SKILL.md')).toContain('the body')
        expect(await bundles.readText(revisionId, 'skills/triage/references/api.md')).toBe('# API')
    })

    it('PUT /revisions/:id/skills/:id rejects a companion path escaping the skill folder', async () => {
        const { app, bundles, revisionId } = await mkRevisionApp()
        const res = await request(app)
            .put(`/revisions/${revisionId}/skills/triage`)
            .send({ description: 'd', body: 'b', files: [{ path: '../escape.md', content: 'x' }] })
        expect(res.status).toBe(400)
        expect(res.body.error).toBe('invalid_skill_file_path')
        // Invalid input must not have cleared/written anything.
        expect(await bundles.exists(revisionId, 'skills/triage/SKILL.md')).toBe(false)
    })

    it('PUT /revisions/:id/skills/:id re-PUT sweeps stale companions', async () => {
        const { app, bundles, revisionId } = await mkRevisionApp()
        await request(app)
            .put(`/revisions/${revisionId}/skills/triage`)
            .send({ description: 'd', body: 'b', files: [{ path: 'old.md', content: '1' }] })
        await request(app)
            .put(`/revisions/${revisionId}/skills/triage`)
            .send({ description: 'd', body: 'b2', files: [{ path: 'new.md', content: '2' }] })
        expect(await bundles.exists(revisionId, 'skills/triage/old.md')).toBe(false)
        expect(await bundles.readText(revisionId, 'skills/triage/new.md')).toBe('2')
    })

    // The single-file `/file` and bulk `/bundle` (with `mode`) endpoints
    // were removed alongside the typed bundle rollout. End-to-end coverage
    // of the typed endpoints lives in
    // `services/agent-tests/src/cases/typed-bundle-authoring.test.ts`.

    it('POST /revisions/:id/freeze returns the sha + state hint, writes the S3 frozen marker, and does NOT mutate agent_revision', async () => {
        const { app, bundles, revisions, revisionId } = await mkRevisionApp()
        await bundles.write(revisionId, 'agent.md', 'final')
        const res = await request(app).post(`/revisions/${revisionId}/freeze`)
        expect(res.status).toBe(200)
        expect(res.body.state).toBe('ready')
        expect(res.body.bundle_sha256).toMatch(/^[0-9a-f]{64}$/)
        // Janitor is no longer a writer to `agent_revision.state` /
        // `bundle_sha256` — Django stamps those inside its own freeze
        // transaction using the returned sha. The bundle store's .frozen
        // marker is still written here; subsequent writes refuse.
        const after = await revisions.getRevision(revisionId)
        expect(after!.state).toBe('draft')
        expect(after!.bundle_sha256).toBeNull()
    })

    it('refuses writes once the revision is frozen', async () => {
        const { app, bundles, revisionId } = await mkRevisionApp()
        await bundles.write(revisionId, 'agent.md', 'final')
        await request(app).post(`/revisions/${revisionId}/freeze`)
        // The typed agent_md PUT enforces the same draft-only contract that
        // the legacy /file PUT did.
        const put = await request(app).put(`/revisions/${revisionId}/agent_md`).send({ content: 'x' })
        expect(put.status).toBe(409)
        expect(put.body.error).toBe('revision_not_draft')
    })

    it('POST /revisions/:id/clone_from copies every file from the source', async () => {
        const { app, bundles, revisions, revisionId } = await mkRevisionApp()
        // Make the existing revision the source — seed it with files, freeze it.
        await bundles.write(revisionId, 'agent.md', 'parent')
        await bundles.write(revisionId, 'skills/x.md', 'parent skill')
        await request(app).post(`/revisions/${revisionId}/freeze`)
        // Create a fresh draft to clone into.
        const apps = await revisions.listApplications(1)
        const draft = await revisions.createRevision({
            application_id: apps[0].id,
            parent_revision_id: revisionId,
            created_by_id: null,
            bundle_uri: 'mem://b2',
            spec: { model: 'test/x' } as never,
        })
        const res = await request(app)
            .post(`/revisions/${draft.id}/clone_from`)
            .send({ source_revision_id: revisionId })
        expect(res.status).toBe(200)
        const paths = (res.body.files as Array<{ path: string }>).map((f) => f.path).sort()
        expect(paths).toEqual(['agent.md', 'skills/x.md'])
    })

    /**
     * Regression: spec drift in a draft row must not block the re-seed path
     * that's about to overwrite it. Before this was fixed, both
     * `clone_from` and `put_bundle` ran `AgentSpecSchema.parse()` on read,
     * so a drafted-then-tightened spec (chat trigger missing `auth`) made
     * `requireDraft` / `assertDraft` return 400 invalid_request — and the
     * seed flow that copies the live spec onto a fresh draft via Django's
     * `new_draft` would deadlock on it forever.
     */
    it('POST /revisions/:id/clone_from still works when the draft has a drifted spec', async () => {
        const { app, bundles, revisions, revisionId } = await mkRevisionApp()
        await bundles.write(revisionId, 'agent.md', 'parent')
        await request(app).post(`/revisions/${revisionId}/freeze`)
        const apps = await revisions.listApplications(1)
        // Insert a draft directly via SQL with a spec that AgentSpecSchema
        // would reject (chat trigger without `auth`). Bypasses
        // createRevision's post-insert parse on purpose.
        const draftId = randomUUID()
        await pool.query(
            `INSERT INTO agent_revision (id, application_id, parent_revision_id, created_by_id,
                                          state, bundle_uri, bundle_sha256, spec)
             VALUES ($1, $2, $3, NULL, 'draft', 'mem://b2', NULL, $4::jsonb)`,
            [
                draftId,
                apps[0].id,
                revisionId,
                JSON.stringify({
                    models: { mode: 'manual', models: [{ model: 'test/x' }] },
                    triggers: [{ type: 'chat', config: {} }], // missing `auth`
                }),
            ]
        )
        const res = await request(app).post(`/revisions/${draftId}/clone_from`).send({ source_revision_id: revisionId })
        expect(res.status).toBe(200)
    })

    /**
     * Same regression on the put-bundle path: `assertDraft` would 400 on a
     * drifted draft, and `persistAuthorSpec` would explode reading
     * `rev.spec` even though it overlays every author field on top. The
     * author payload itself is parsed strictly, so the merged result is
     * still validated — drift only stops blocking the read, not the write.
     */
    it('PUT /revisions/:id/bundle still works when the draft has a drifted spec', async () => {
        const { app, revisions, revisionId } = await mkRevisionApp()
        const apps = await revisions.listApplications(1)
        const draftId = randomUUID()
        await pool.query(
            `INSERT INTO agent_revision (id, application_id, parent_revision_id, created_by_id,
                                          state, bundle_uri, bundle_sha256, spec)
             VALUES ($1, $2, $3, NULL, 'draft', 'mem://b3', NULL, $4::jsonb)`,
            [
                draftId,
                apps[0].id,
                revisionId,
                JSON.stringify({
                    models: { mode: 'manual', models: [{ model: 'test/x' }] },
                    triggers: [{ type: 'chat', config: {} }], // missing `auth`
                }),
            ]
        )
        const res = await request(app)
            .put(`/revisions/${draftId}/bundle`)
            .send({
                agent_md: 'hello',
                skills: [],
                tools: [],
                spec: {
                    models: { mode: 'manual', models: [{ model: 'test/y' }] },
                    triggers: [
                        {
                            type: 'chat',
                            config: {},
                            auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] },
                        },
                    ],
                },
            })
        expect(res.status).toBe(200)
        // Confirm the bad spec was actually replaced — getRevision will
        // parse it strictly, so a successful read proves the merge wrote a
        // valid spec.
        const after = await revisions.getRevision(draftId)
        expect(after?.spec.models).toEqual({ mode: 'manual', models: [{ model: 'test/y' }], optimize_for: 'cost' })
    })

    it('returns 503 when the revision/bundle stores are not configured', async () => {
        const { app } = mk() // no revisions/bundles
        const res = await request(app).get('/revisions/00000000-0000-0000-0000-000000000000/manifest')
        expect(res.status).toBe(503)
    })

    /**
     * Perf regression tests. We can't assert wall-clock latency reliably in CI
     * (network jitter against SeaweedFS), so the tests assert on the structural
     * invariants that USED to be violated:
     *
     *   - `clone_from` should issue its per-file `bundle.copy` calls in parallel,
     *     not serially. We measure max concurrency, not total time.
     *   - The freeze pipeline (derive + freeze) should only call `bundle.list`
     *     once. Each `list` is a ListObjects + N parallel HEADs on S3 —
     *     repeated calls were the dominant cost.
     *
     * Both invariants previously broke and burned 30s+ on a 15-file bundle,
     * timing out the Django proxy mid-freeze.
     */
    describe('perf regressions', () => {
        /**
         * Wraps an S3BundleStore so callers can observe `list` call count and
         * `copy` peak concurrency. Identity on every other method. Used only
         * by the perf-regression tests.
         */
        function instrument(store: S3BundleStore): {
            store: S3BundleStore
            listCalls: { count: number }
            copyConcurrency: { peak: number }
        } {
            const listCalls = { count: 0 }
            const copyConcurrency = { peak: 0 }
            let inFlight = 0
            const wrapped = new Proxy(store, {
                get(target, prop, receiver) {
                    if (prop === 'list') {
                        return async (
                            ...args: Parameters<S3BundleStore['list']>
                        ): Promise<ReturnType<S3BundleStore['list']>> => {
                            listCalls.count++
                            return Reflect.get(target, prop, receiver).apply(target, args)
                        }
                    }
                    if (prop === 'copy') {
                        return async (
                            ...args: Parameters<S3BundleStore['copy']>
                        ): Promise<ReturnType<S3BundleStore['copy']>> => {
                            inFlight++
                            if (inFlight > copyConcurrency.peak) {
                                copyConcurrency.peak = inFlight
                            }
                            try {
                                return await Reflect.get(target, prop, receiver).apply(target, args)
                            } finally {
                                inFlight--
                            }
                        }
                    }
                    return Reflect.get(target, prop, receiver)
                },
            })
            return { store: wrapped as S3BundleStore, listCalls, copyConcurrency }
        }

        async function mkInstrumentedApp(): Promise<{
            app: ReturnType<typeof buildJanitorApp>
            bundles: S3BundleStore
            revisions: PgRevisionStore
            revisionId: string
            listCalls: { count: number }
            copyConcurrency: { peak: number }
        }> {
            const revisions = new PgRevisionStore(pool)
            const queue = new PgSessionQueue(pool)
            const apprec = await revisions.createApplication({ team_id: 1, slug: 'p', name: 'P', description: '' })
            const rev = await revisions.createRevision({
                application_id: apprec.id,
                parent_revision_id: null,
                created_by_id: null,
                bundle_uri: 'mem://b',
                spec: AgentSpecSchema.parse({
                    models: { mode: 'manual', models: [{ model: 'test/x' }] },
                    triggers: [
                        {
                            type: 'chat',
                            config: {},
                            auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] },
                        },
                    ],
                }),
            })
            const instrumented = instrument(bundleStore)
            const app = buildJanitorApp({
                queue,
                sweep: { queue, stuckRunningThresholdMs: 60_000 },
                revisions,
                bundles: instrumented.store,
            })
            return {
                app,
                bundles: instrumented.store,
                revisions,
                revisionId: rev.id,
                listCalls: instrumented.listCalls,
                copyConcurrency: instrumented.copyConcurrency,
            }
        }

        it('clone_from issues bundle.copy calls in parallel (peak concurrency > 1)', async () => {
            const { app, bundles, revisions, revisionId, copyConcurrency } = await mkInstrumentedApp()
            // Seed a multi-file source so any serialization is observable.
            for (let i = 0; i < 8; i++) {
                await bundles.write(revisionId, `skills/s${i}.md`, `body ${i}`)
            }
            await bundles.write(revisionId, 'agent.md', 'top')
            await request(app).post(`/revisions/${revisionId}/freeze`)

            const draft = await revisions.createRevision({
                application_id: (await revisions.listApplications(1))[0].id,
                parent_revision_id: revisionId,
                created_by_id: null,
                bundle_uri: 'mem://b2',
                spec: { model: 'test/x' } as never,
            })
            // Reset the peak after the freeze step's own copies — clone_from
            // is the only call we want to measure here.
            copyConcurrency.peak = 0

            const res = await request(app)
                .post(`/revisions/${draft.id}/clone_from`)
                .send({ source_revision_id: revisionId })
            expect(res.status).toBe(200)
            // Serial would mean peak = 1. Parallel sees most/all copies
            // overlap; we conservatively assert > 1, which is what regresses
            // if someone reintroduces a `for await` loop.
            expect(copyConcurrency.peak).toBeGreaterThan(1)
        })

        it('freeze pipeline calls bundle.list at most twice (one for derive+freeze, one for the idempotent isFrozen-pre-check is allowed)', async () => {
            const { app, bundles, revisionId, listCalls } = await mkInstrumentedApp()
            // Populate so list() actually does work (vs an empty bundle).
            for (let i = 0; i < 8; i++) {
                await bundles.write(revisionId, `skills/s${i}.md`, `body ${i}`)
            }
            await bundles.write(revisionId, 'agent.md', 'top')

            // Reset after the writes (they don't call list, but in case
            // any future write path does).
            listCalls.count = 0

            const res = await request(app).post(`/revisions/${revisionId}/freeze`)
            expect(res.status).toBe(200)
            // The freeze handler now calls list ONCE up front and threads
            // the result into deriveAndPersistSpec (→ readTypedBundle) and
            // bundles.freeze(precomputedEntries). The validate step calls
            // bundle.exists() not list(). If someone reintroduces a re-list
            // in any of those paths, this count breaks.
            // We allow 1 (the cached path) — the test is a regression
            // pin, not a hard guarantee that future refactors can't change.
            expect(listCalls.count).toBeLessThanOrEqual(1)
        })

        it('freeze of an empty bundle still completes in one list call (no degenerate-case re-walk)', async () => {
            const { app, revisionId, listCalls } = await mkInstrumentedApp()
            // No writes — just agent.md so validate doesn't 422 on missing
            // entrypoint.
            await bundleStore.write(revisionId, 'agent.md', 'top')
            listCalls.count = 0
            const res = await request(app).post(`/revisions/${revisionId}/freeze`)
            expect(res.status).toBe(200)
            expect(listCalls.count).toBeLessThanOrEqual(1)
        })
    })
})
