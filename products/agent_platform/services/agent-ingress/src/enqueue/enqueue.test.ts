import { randomUUID } from 'node:crypto'
import { Pool } from 'pg'

import { AgentSpecSchema, PgSessionQueue, SessionPrincipal } from '@posthog/agent-shared'
import type { AgentApplication, AgentRevision } from '@posthog/agent-shared'
import { reset } from '@posthog/agent-shared/testing'

import { enqueueOrResume } from './enqueue'

const TEST_DB_URL =
    process.env.AGENT_TEST_DB_URL ?? 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue_test'
let pool: Pool
beforeAll(() => {
    pool = new Pool({ connectionString: TEST_DB_URL })
})
afterAll(async () => {
    await pool.end()
})
beforeEach(async () => {
    await reset({ databaseUrl: TEST_DB_URL })
})

function makePair(): { app: AgentApplication; rev: AgentRevision } {
    // PG schema requires UUID-shaped ids on agent_session.application_id /
    // revision_id (no FK constraint, just type). Synthetic uuids per test.
    const appId = randomUUID()
    const revId = randomUUID()
    const app = {
        id: appId,
        team_id: 1,
        slug: 'x',
        name: 'X',
        description: '',
        live_revision_id: revId,
        archived: false,
        encrypted_env: null,
    }
    const rev = {
        id: revId,
        application_id: app.id,
        parent_revision_id: null,
        created_by_id: null,
        created_at: 'now',
        state: 'live' as const,
        bundle_uri: 's3://x/',
        bundle_sha256: null,
        spec: AgentSpecSchema.parse({ model: 'test/x' }),
        encrypted_env: null,
    }
    return { app, rev }
}

const ALICE: SessionPrincipal = { kind: 'slack', workspace_id: 'T1', slack_user_id: 'user-alice' }
const BOB: SessionPrincipal = { kind: 'slack', workspace_id: 'T1', slack_user_id: 'user-bob' }

// Slack-trigger sessions must carry full metadata (workspace/channel/ts/thread_ts);
// `bareTriggerMetadata` no longer accepts a bare `{ kind: 'slack' }`.
const SLACK_META = { kind: 'slack' as const, workspace_id: 'T1', channel: 'C01', ts: '1', thread_ts: '4' }

describe('enqueueOrResume', () => {
    it('creates a fresh session without externalKey', async () => {
        const queue = new PgSessionQueue(pool)
        const { app, rev } = makePair()
        const out = await enqueueOrResume(
            { queue },
            {
                application: app,
                revision: rev,
                externalKey: null,
                seed: { role: 'user', content: 'hi', timestamp: Date.now() },
            }
        )
        expect(out.kind).toBe('created')
        expect(out.isResume).toBe(false)
    })

    it('resumes an existing session matching externalKey + same principal', async () => {
        const queue = new PgSessionQueue(pool)
        const { app, rev } = makePair()
        const first = await enqueueOrResume(
            { queue },
            {
                application: app,
                revision: rev,
                externalKey: 'slack:C01:thread1',
                seed: { role: 'user', content: 'first', timestamp: Date.now() },
                principal: ALICE,
            }
        )
        const second = await enqueueOrResume(
            { queue },
            {
                application: app,
                revision: rev,
                externalKey: 'slack:C01:thread1',
                seed: { role: 'user', content: 'follow-up', timestamp: Date.now() },
                principal: ALICE,
            }
        )
        expect(second.kind).toBe('resumed')
        expect(second.sessionId).toBe(first.sessionId)
        const session = await queue.get(first.sessionId)
        // Initial seed in conversation; follow-up lands in pending_inputs so
        // the runner drains it at the start of the next turn.
        expect(session!.conversation).toHaveLength(1)
        expect(session!.pending_inputs).toHaveLength(1)
    })

    it('resumes a `completed` (open) session via external_key', async () => {
        // Under the new state machine `completed` is the open idle state —
        // external_key reuse picks it back up. Only `closed` / `failed`
        // force a fresh session.
        const queue = new PgSessionQueue(pool)
        const { app, rev } = makePair()
        const first = await enqueueOrResume(
            { queue },
            {
                application: app,
                revision: rev,
                externalKey: 'slack:C01:thread2',
                seed: { role: 'user', content: 'first', timestamp: Date.now() },
                principal: ALICE,
            }
        )
        await queue.update(first.sessionId, { state: 'completed' })
        const second = await enqueueOrResume(
            { queue },
            {
                application: app,
                revision: rev,
                externalKey: 'slack:C01:thread2',
                seed: { role: 'user', content: 'second', timestamp: Date.now() },
                principal: ALICE,
            }
        )
        expect(second.kind).toBe('resumed')
        expect(second.sessionId).toBe(first.sessionId)
    })

    it('creates a new session if existing one is `closed` (terminal)', async () => {
        const queue = new PgSessionQueue(pool)
        const { app, rev } = makePair()
        const first = await enqueueOrResume(
            { queue },
            {
                application: app,
                revision: rev,
                externalKey: 'slack:C01:thread3',
                seed: { role: 'user', content: 'first', timestamp: Date.now() },
                principal: ALICE,
            }
        )
        await queue.update(first.sessionId, { state: 'closed' })
        const second = await enqueueOrResume(
            { queue },
            {
                application: app,
                revision: rev,
                externalKey: 'slack:C01:thread3',
                seed: { role: 'user', content: 'second', timestamp: Date.now() },
                principal: ALICE,
            }
        )
        expect(second.kind).toBe('created')
        expect(second.sessionId).not.toBe(first.sessionId)
    })

    it('denies a resume when the incoming principal does not match', async () => {
        // The Slack-thread security gap: previously a second user could
        // resume someone else's thread because principals weren't checked on
        // the externalKey resume path. Now we record a pending elevation
        // request and surface elevation_required to the trigger instead.
        const queue = new PgSessionQueue(pool)
        const { app, rev } = makePair()
        const first = await enqueueOrResume(
            { queue },
            {
                application: app,
                revision: rev,
                externalKey: 'slack:C01:thread4',
                seed: { role: 'user', content: 'alice opens thread', timestamp: Date.now() },
                principal: ALICE,
                trigger: 'slack',
                triggerMetadata: SLACK_META,
            }
        )
        const second = await enqueueOrResume(
            { queue },
            {
                application: app,
                revision: rev,
                externalKey: 'slack:C01:thread4',
                seed: { role: 'user', content: 'bob replies', timestamp: Date.now() },
                principal: BOB,
                trigger: 'slack',
                triggerMetadata: SLACK_META,
            }
        )
        expect(second.kind).toBe('elevation_required')
        if (second.kind !== 'elevation_required') {
            return
        }
        expect(second.sessionId).toBe(first.sessionId)
        expect(second.elevationRequestId).toMatch(/.+/)

        const session = await queue.get(first.sessionId)
        // The rejected message is NOT appended to pending_inputs — the
        // runner must not see it.
        expect(session!.pending_inputs).toHaveLength(0)
        // It IS preserved on the elevation request for replay-on-grant.
        expect(session!.pending_elevation_requests).toHaveLength(1)
        const req = session!.pending_elevation_requests[0]
        expect(req.state).toBe('pending')
        expect(req.requester.kind === 'slack' && req.requester.slack_user_id).toBe('user-bob')
        const proposed = req.proposed_message
        expect(proposed.role).toBe('user')
        if (proposed.role === 'user') {
            expect(proposed.content).toBe('bob replies')
        }
    })

    it('isolates by revision: a request for a draft does not resume a session on another revision sharing the external_key', async () => {
        // Resume is revision-scoped. `findByExternalKey` matches only sessions
        // on the request's revision, so a draft-preview request can't resume a
        // session created on the live (or a different draft) revision under the
        // same external_key — it opens its own session instead.
        const queue = new PgSessionQueue(pool)
        const { app, rev } = makePair()
        const draftRev: AgentRevision = { ...rev, id: randomUUID(), state: 'draft' }
        const live = await enqueueOrResume(
            { queue },
            {
                application: app,
                revision: rev,
                externalKey: 'slack:C01:thread-iso',
                seed: { role: 'user', content: 'live opens thread', timestamp: Date.now() },
                principal: ALICE,
                trigger: 'slack',
                triggerMetadata: SLACK_META,
            }
        )
        const preview = await enqueueOrResume(
            { queue },
            {
                application: app,
                revision: draftRev,
                externalKey: 'slack:C01:thread-iso',
                seed: { role: 'user', content: 'preview author tests draft', timestamp: Date.now() },
                principal: ALICE,
                trigger: 'slack',
                triggerMetadata: SLACK_META,
            }
        )
        expect(preview.kind).toBe('created')
        expect(preview.sessionId).not.toBe(live.sessionId)
        // The new session is its own row on the draft revision — the live
        // session is untouched.
        const previewSession = await queue.get(preview.sessionId)
        expect(previewSession!.revision_id).toBe(draftRev.id)
        const liveSession = await queue.get(live.sessionId)
        expect(liveSession!.pending_inputs).toHaveLength(0)
        // A second request on the same key + same (live) revision resumes the
        // live row — the draft row doesn't poach it.
        const liveAgain = await enqueueOrResume(
            { queue },
            {
                application: app,
                revision: rev,
                externalKey: 'slack:C01:thread-iso',
                seed: { role: 'user', content: 'live follow-up', timestamp: Date.now() },
                principal: ALICE,
                trigger: 'slack',
                triggerMetadata: SLACK_META,
            }
        )
        expect(liveAgain.kind).toBe('resumed')
        expect(liveAgain.sessionId).toBe(live.sessionId)
        // Two different draft revisions on the same external_key get distinct
        // sessions — their conversation histories don't bleed.
        const secondDraftRev: AgentRevision = { ...rev, id: randomUUID(), state: 'draft' }
        const otherPreview = await enqueueOrResume(
            { queue },
            {
                application: app,
                revision: secondDraftRev,
                externalKey: 'slack:C01:thread-iso',
                seed: { role: 'user', content: 'other draft', timestamp: Date.now() },
                principal: ALICE,
                trigger: 'slack',
                triggerMetadata: SLACK_META,
            }
        )
        expect(otherPreview.kind).toBe('created')
        expect(otherPreview.sessionId).not.toBe(preview.sessionId)
    })

    it('expires the oldest pending elevation request once the cap is exceeded', async () => {
        const queue = new PgSessionQueue(pool)
        const { app, rev } = makePair()
        await enqueueOrResume(
            { queue },
            {
                application: app,
                revision: rev,
                externalKey: 'slack:C01:thread5',
                seed: { role: 'user', content: 'alice opens', timestamp: Date.now() },
                principal: ALICE,
                trigger: 'slack',
                triggerMetadata: SLACK_META,
            }
        )
        // Six denials — the seventh would also fit if we ever lift the cap,
        // but here we just exercise the rollover from 5 → 5.
        for (let i = 0; i < 6; i++) {
            await enqueueOrResume(
                { queue },
                {
                    application: app,
                    revision: rev,
                    externalKey: 'slack:C01:thread5',
                    seed: { role: 'user', content: `bob #${i}`, timestamp: Date.now() + i },
                    principal: { ...BOB, slack_user_id: `bob-${i}` },
                    trigger: 'slack',
                    triggerMetadata: SLACK_META,
                }
            )
        }
        const session = await queue.get((await queue.findByExternalKey(app.id, 'slack:C01:thread5', rev.id))!.id)
        const pendings = session!.pending_elevation_requests.filter((r) => r.state === 'pending')
        expect(pendings).toHaveLength(5)
        const expired = session!.pending_elevation_requests.filter((r) => r.state === 'expired')
        expect(expired).toHaveLength(1)
    })

    describe('idempotency_key', () => {
        it('creates the session on first call with a key', async () => {
            const queue = new PgSessionQueue(pool)
            const { app, rev } = makePair()
            const out = await enqueueOrResume(
                { queue },
                {
                    application: app,
                    revision: rev,
                    externalKey: null,
                    idempotencyKey: 'cron:rev1:digest:1780346400000',
                    seed: { role: 'user', content: 'hi', timestamp: Date.now() },
                }
            )
            expect(out.kind).toBe('created')
            const session = await queue.get(out.sessionId)
            expect(session!.idempotency_key).toBe('cron:rev1:digest:1780346400000')
        })

        it('returns the original session id on a duplicate call — no append, no resume, no new row', async () => {
            const queue = new PgSessionQueue(pool)
            const { app, rev } = makePair()
            const first = await enqueueOrResume(
                { queue },
                {
                    application: app,
                    revision: rev,
                    externalKey: null,
                    idempotencyKey: 'k1',
                    seed: { role: 'user', content: 'first', timestamp: 1 },
                }
            )
            const second = await enqueueOrResume(
                { queue },
                {
                    application: app,
                    revision: rev,
                    externalKey: null,
                    idempotencyKey: 'k1',
                    // Deliberately different seed to prove it's discarded.
                    seed: { role: 'user', content: 'second', timestamp: 2 },
                }
            )
            expect(second.sessionId).toBe(first.sessionId)
            expect(second.kind).toBe('created')
            expect(second.isResume).toBe(false)
            // The first call's seed is preserved; the duplicate's seed is dropped.
            const session = await queue.get(first.sessionId)
            expect(session!.conversation).toHaveLength(1)
            expect((session!.conversation[0] as { content: string }).content).toBe('first')
        })

        it('stamps trigger_metadata on the session row when supplied', async () => {
            const queue = new PgSessionQueue(pool)
            const { app, rev } = makePair()
            const out = await enqueueOrResume(
                { queue },
                {
                    application: app,
                    revision: rev,
                    externalKey: null,
                    idempotencyKey: 'k2',
                    triggerMetadata: {
                        kind: 'cron',
                        cron_name: 'digest',
                        schedule: '0 9 * * MON',
                        fired_at: '2026-06-01T16:00:00Z',
                    },
                    seed: { role: 'user', content: 'hi', timestamp: 0 },
                }
            )
            const session = await queue.get(out.sessionId)
            expect(session!.trigger_metadata).toEqual({
                kind: 'cron',
                cron_name: 'digest',
                schedule: '0 9 * * MON',
                fired_at: '2026-06-01T16:00:00Z',
            })
        })

        it('stamps the trigger kind from the trigger arg when no explicit metadata is supplied', async () => {
            const queue = new PgSessionQueue(pool)
            const { app, rev } = makePair()
            const out = await enqueueOrResume(
                { queue },
                {
                    application: app,
                    revision: rev,
                    externalKey: null,
                    idempotencyKey: 'k-webhook',
                    trigger: 'webhook',
                    seed: { role: 'user', content: 'hi', timestamp: 0 },
                }
            )
            const session = await queue.get(out.sessionId)
            // Every session is attributable to its source for the console badge + filter.
            expect(session!.trigger_metadata).toEqual({ kind: 'webhook' })
        })

        it('defaults the stamped trigger kind to chat', async () => {
            const queue = new PgSessionQueue(pool)
            const { app, rev } = makePair()
            const out = await enqueueOrResume(
                { queue },
                {
                    application: app,
                    revision: rev,
                    externalKey: null,
                    idempotencyKey: 'k-default',
                    seed: { role: 'user', content: 'hi', timestamp: 0 },
                }
            )
            const session = await queue.get(out.sessionId)
            expect(session!.trigger_metadata).toEqual({ kind: 'chat' })
        })

        it('idempotency_key and external_key compose: idempotency wins on collision', async () => {
            // A request with both keys, where the idempotency_key matches an
            // existing row. The dedupe path returns the original; the
            // external_key resume path doesn't fire.
            const queue = new PgSessionQueue(pool)
            const { app, rev } = makePair()
            const first = await enqueueOrResume(
                { queue },
                {
                    application: app,
                    revision: rev,
                    externalKey: 'thread-1',
                    idempotencyKey: 'req-A',
                    seed: { role: 'user', content: 'first', timestamp: 0 },
                }
            )
            const second = await enqueueOrResume(
                { queue },
                {
                    application: app,
                    revision: rev,
                    externalKey: 'thread-1',
                    idempotencyKey: 'req-A',
                    seed: { role: 'user', content: 'second', timestamp: 1 },
                }
            )
            expect(second.sessionId).toBe(first.sessionId)
            // No append happened — the seed got dropped along with the
            // duplicate request.
            const session = await queue.get(first.sessionId)
            expect(session!.pending_inputs).toHaveLength(0)
            expect(session!.conversation).toHaveLength(1)
        })

        it('races: unique-violation on insert resolves to the original session id', async () => {
            // Simulates the window between findByIdempotencyKey and INSERT:
            // a concurrent writer landed a row first. The wrapped queue throws
            // the PG unique-violation code on the second insert.
            const queue = new PgSessionQueue(pool)
            const { app, rev } = makePair()
            // First call goes through normally; capture its id.
            const first = await enqueueOrResume(
                { queue },
                {
                    application: app,
                    revision: rev,
                    externalKey: null,
                    idempotencyKey: 'race-k',
                    seed: { role: 'user', content: 'a', timestamp: 0 },
                }
            )
            // Wrap the queue to: (a) hide the existing key from the
            // pre-check (simulating the "didn't see it yet" window), (b)
            // throw unique-violation on enqueue.
            // Counter lives outside the Proxy handler because `get` is
            // re-invoked per property access, so a per-handler closure
            // would reset between the pre-check and the recovery lookup.
            let findCalls = 0
            const racyQueue = new Proxy(queue, {
                get(target, prop, recv) {
                    if (prop === 'findByIdempotencyKey') {
                        return async (appId: string, key: string) => {
                            findCalls++
                            // First call (the pre-check) returns null; second
                            // call (the post-violation lookup) returns the row.
                            if (findCalls === 1) {
                                return null
                            }
                            return target.findByIdempotencyKey(appId, key)
                        }
                    }
                    if (prop === 'enqueue') {
                        return async (_session: unknown) => {
                            const err = new Error('duplicate key value violates unique constraint') as Error & {
                                code: string
                            }
                            err.code = '23505'
                            throw err
                        }
                    }
                    const v = Reflect.get(target, prop, recv)
                    return typeof v === 'function' ? v.bind(target) : v
                },
            })
            const second = await enqueueOrResume(
                { queue: racyQueue },
                {
                    application: app,
                    revision: rev,
                    externalKey: null,
                    idempotencyKey: 'race-k',
                    seed: { role: 'user', content: 'b', timestamp: 1 },
                }
            )
            expect(second.kind).toBe('created')
            expect(second.sessionId).toBe(first.sessionId)
        })

        it('without a key: unique-violation propagates (the original bug surface)', async () => {
            // Without an idempotency_key supplied, a unique-violation has
            // nothing to resolve against — should rethrow rather than
            // silently swallow.
            const queue = new PgSessionQueue(pool)
            const { app, rev } = makePair()
            const racyQueue = new Proxy(queue, {
                get(target, prop, recv) {
                    if (prop === 'enqueue') {
                        return async () => {
                            const err = new Error('boom') as Error & { code: string }
                            err.code = '23505'
                            throw err
                        }
                    }
                    const v = Reflect.get(target, prop, recv)
                    return typeof v === 'function' ? v.bind(target) : v
                },
            })
            await expect(
                enqueueOrResume(
                    { queue: racyQueue },
                    {
                        application: app,
                        revision: rev,
                        externalKey: null,
                        seed: { role: 'user', content: 'x', timestamp: 0 },
                    }
                )
            ).rejects.toThrow('boom')
        })
    })

    describe('bareTriggerMetadata exhaustiveness', () => {
        it('throws if a slack trigger is enqueued without triggerMetadata', async () => {
            const queue = new PgSessionQueue(pool)
            const { app, rev } = makePair()
            await expect(
                enqueueOrResume(
                    { queue },
                    {
                        application: app,
                        revision: rev,
                        externalKey: null,
                        trigger: 'slack',
                        seed: { role: 'user', content: 'hi', timestamp: Date.now() },
                    }
                )
            ).rejects.toThrow(/slack trigger requires explicit triggerMetadata/)
        })

        it.each([
            ['webhook', 'webhook'],
            ['mcp', 'mcp'],
            ['chat', 'chat'],
        ] as const)('stamps bare {kind:%s} when trigger=%s and no triggerMetadata', async (kind, trigger) => {
            const queue = new PgSessionQueue(pool)
            const { app, rev } = makePair()
            const out = await enqueueOrResume(
                { queue },
                {
                    application: app,
                    revision: rev,
                    externalKey: null,
                    trigger,
                    seed: { role: 'user', content: 'hi', timestamp: Date.now() },
                }
            )
            expect(out.kind).toBe('created')
            const session = await queue.get(out.sessionId)
            expect(session!.trigger_metadata).toEqual({ kind })
        })
    })
})
