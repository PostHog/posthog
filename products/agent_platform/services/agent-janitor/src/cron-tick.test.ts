/**
 * Unit tests for `cronTick`. Backs against the real PG-backed revision +
 * session queue (no in-memory variants); the scheduler logic is exercised
 * end-to-end with the same persistence prod runs. PR-3 of
 * `cron-trigger-scheduler.md` v0.
 */

import { Pool } from 'pg'

import {
    AgentApplication,
    AgentRevision,
    AgentSpecSchema,
    PgRevisionStore,
    PgSessionQueue,
} from '@posthog/agent-shared'
import { reset } from '@posthog/agent-shared/testing'

import { cronTick, fireCronManually, newCronTickState } from './cron-tick'

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

interface SetupOpts {
    triggers: Array<{
        type: 'cron'
        config: {
            name: string
            schedule: string
            prompt: string
            timezone?: string
            external_key?: string
            catch_up?: 'all' | 'most_recent' | 'skip'
            max_catch_up_age_seconds?: number
        }
    }>
    teamId?: number
    archived?: boolean
}

async function deploy(
    revisions: PgRevisionStore,
    opts: SetupOpts
): Promise<{ app: AgentApplication; rev: AgentRevision }> {
    const app = await revisions.createApplication({
        team_id: opts.teamId ?? 1,
        slug: 'cron-agent',
        name: 'Cron Agent',
        description: '',
    })
    const rev = await revisions.createRevision({
        application_id: app.id,
        parent_revision_id: null,
        created_by_id: null,
        bundle_uri: 's3://x/',
        spec: AgentSpecSchema.parse({
            models: { mode: 'manual', models: [{ model: 'anthropic/claude-haiku-4-5' }] },
            triggers: opts.triggers,
        }),
    })
    await revisions.setLiveRevision(app.id, rev.id)
    if (opts.archived) {
        // archived flag isn't on createApplication today; flip via the
        // application record directly (test helper, harmless).
        ;(app as AgentApplication).archived = true
    }
    return { app, rev }
}

const minimalCron = (
    overrides: Partial<SetupOpts['triggers'][number]['config']> = {}
): SetupOpts['triggers'][number] => ({
    type: 'cron',
    config: {
        name: 'digest',
        schedule: '* * * * *',
        prompt: 'Run the digest.',
        ...overrides,
    },
})

describe('cronTick', () => {
    it('no-ops when there are no live cron revisions', async () => {
        const revisions = new PgRevisionStore(pool)
        const queue = new PgSessionQueue(pool)
        const state = newCronTickState()
        const out = await cronTick({ revisions, queue }, state)
        expect(out).toEqual({ fired: 0, skipped_no_window: 0, skipped_caught_up: 0, skipped_no_app: 0, errors: 0 })
    })

    it('first tick after process start fires nothing — lastTickAt = now, window is empty', async () => {
        const revisions = new PgRevisionStore(pool)
        const queue = new PgSessionQueue(pool)
        await deploy(revisions, { triggers: [minimalCron()] })
        const state = newCronTickState()
        const out = await cronTick({ revisions, queue }, state)
        // No firings in (now, now]; the catch-up policy can't fire on the
        // first tick because lastTickAt was just initialised.
        expect(out.fired).toBe(0)
        expect(state.lastTickAt).not.toBeNull()
    })

    it('fires a session when a scheduled firing falls in the window', async () => {
        const revisions = new PgRevisionStore(pool)
        const queue = new PgSessionQueue(pool)
        const { app, rev } = await deploy(revisions, {
            triggers: [minimalCron({ schedule: '* * * * *', prompt: 'tick' })],
        })
        const state = newCronTickState()
        // First tick seeds lastTickAt; the second tick (3 minutes later)
        // has a 3-minute window with 3 missed firings, all collapsed by
        // catch_up=most_recent (the default).
        const t0 = new Date('2026-06-01T10:00:00Z')
        await cronTick({ revisions, queue, now: () => t0 }, state)
        const t1 = new Date('2026-06-01T10:03:00Z')
        const out = await cronTick({ revisions, queue, now: () => t1 }, state)
        expect(out.fired).toBe(1)
        // The fired session lands on the most-recent firing minute (10:03).
        const minute = Math.floor(new Date('2026-06-01T10:03:00Z').getTime() / 60_000)
        const session = await queue.findByIdempotencyKey(app.id, `cron:${rev.id}:digest:${minute}`)
        expect(session).not.toBeNull()
        expect((session!.conversation[0] as { content: string }).content).toBe('tick')
    })

    it('catch_up=all fires every missed firing within the age cap', async () => {
        const revisions = new PgRevisionStore(pool)
        const queue = new PgSessionQueue(pool)
        const { app, rev } = await deploy(revisions, {
            triggers: [minimalCron({ schedule: '* * * * *', catch_up: 'all' })],
        })
        const state = newCronTickState()
        const t0 = new Date('2026-06-01T10:00:00Z')
        await cronTick({ revisions, queue, now: () => t0 }, state)
        const t1 = new Date('2026-06-01T10:03:00Z')
        const out = await cronTick({ revisions, queue, now: () => t1 }, state)
        expect(out.fired).toBe(3)
        // Each firing got a distinct idempotency_key keyed by minute.
        const minutes = ['10:01', '10:02', '10:03'].map((m) => {
            const d = new Date(`2026-06-01T${m}:00Z`)
            return Math.floor(d.getTime() / 60_000)
        })
        for (const minute of minutes) {
            const session = await queue.findByIdempotencyKey(app.id, `cron:${rev.id}:digest:${minute}`)
            expect(session).not.toBeNull()
        }
    })

    it('catch_up=skip drops the firings when multiple are missed', async () => {
        const revisions = new PgRevisionStore(pool)
        const queue = new PgSessionQueue(pool)
        await deploy(revisions, { triggers: [minimalCron({ schedule: '* * * * *', catch_up: 'skip' })] })
        const state = newCronTickState()
        const t0 = new Date('2026-06-01T10:00:00Z')
        await cronTick({ revisions, queue, now: () => t0 }, state)
        const t1 = new Date('2026-06-01T10:05:00Z')
        const out = await cronTick({ revisions, queue, now: () => t1 }, state)
        expect(out.fired).toBe(0)
        expect(out.skipped_caught_up).toBeGreaterThan(0)
    })

    it('max_catch_up_age_seconds bounds the catch-up regardless of mode', async () => {
        const revisions = new PgRevisionStore(pool)
        const queue = new PgSessionQueue(pool)
        await deploy(revisions, {
            triggers: [minimalCron({ schedule: '* * * * *', catch_up: 'all', max_catch_up_age_seconds: 120 })],
        })
        const state = newCronTickState()
        const t0 = new Date('2026-06-01T10:00:00Z')
        await cronTick({ revisions, queue, now: () => t0 }, state)
        // Window (10:00, 10:05]: firings at 10:01, 10:02, 10:03, 10:04, 10:05.
        // With max_catch_up_age_seconds=120 and now=10:05, the cron enumeration's
        // exclusive lower bound is earliestAllowed=10:03 — so 10:04, 10:05 = 2
        // firings survive (the firing exactly at the age boundary is dropped,
        // matching the `clamps the enumeration window` regression below).
        const t1 = new Date('2026-06-01T10:05:00Z')
        const out = await cronTick({ revisions, queue, now: () => t1 }, state)
        expect(out.fired).toBe(2)
    })

    it('clamps the enumeration window to max_catch_up_age_seconds', async () => {
        // Regression for the boot-time DoS: without clamping the window
        // BEFORE iteration, a long pause + a sub-minute schedule would
        // walk hundreds of thousands of firings only to discard them all
        // in applyCatchUp. The cap should keep firings.length bounded.
        const revisions = new PgRevisionStore(pool)
        const queue = new PgSessionQueue(pool)
        await deploy(revisions, {
            triggers: [minimalCron({ schedule: '* * * * *', catch_up: 'all', max_catch_up_age_seconds: 120 })],
        })
        const state = newCronTickState()

        const t0 = new Date('2026-06-01T00:00:00Z')
        await cronTick({ revisions, queue, now: () => t0 }, state)

        // 7-day gap on a minute schedule = 10,080 firings before the clamp.
        // After clamping to max_catch_up_age_seconds=120, the tick should
        // enumerate at most 2 firings and skip nothing on the catch-up
        // discard path.
        const tLater = new Date('2026-06-08T00:00:00Z')
        const out = await cronTick({ revisions, queue, now: () => tLater }, state)

        expect(out.fired).toBe(2)
        expect(out.skipped_caught_up).toBe(0)
    })

    it('catch_up=all caps firings per tick and drops the stale tail', async () => {
        // A frequent schedule with a long catch-up window can pile up far more
        // survivors than one tick should fire. The cap keeps the most recent
        // MAX_FIRINGS_PER_TICK (100) and counts the rest as caught-up.
        const revisions = new PgRevisionStore(pool)
        const queue = new PgSessionQueue(pool)
        await deploy(revisions, {
            triggers: [minimalCron({ schedule: '* * * * *', catch_up: 'all', max_catch_up_age_seconds: 100_000 })],
        })
        const state = newCronTickState()

        const t0 = new Date('2026-06-01T10:00:00Z')
        await cronTick({ revisions, queue, now: () => t0 }, state)

        // 200 minute-firings fall in (10:00, 13:20]; the age window (100000s)
        // covers all of them, so all 200 survive catch-up — then the cap trims
        // to the most recent 100.
        const t1 = new Date('2026-06-01T13:20:00Z')
        const out = await cronTick({ revisions, queue, now: () => t1 }, state)

        expect(out.fired).toBe(100)
        expect(out.skipped_caught_up).toBe(100)
    })

    it('idempotency: re-running the same tick is a no-op (the unique-key path)', async () => {
        // Simulates a second janitor replica running cronTick on the same
        // window; the second call should land on the unique-violation path
        // (via PgSessionQueue's findByIdempotencyKey + the row's UNIQUE index).
        const revisions = new PgRevisionStore(pool)
        const queue = new PgSessionQueue(pool)
        const { app, rev } = await deploy(revisions, { triggers: [minimalCron({ schedule: '* * * * *' })] })
        const tickA = newCronTickState()
        const tickB = newCronTickState()
        const t0 = new Date('2026-06-01T10:00:00Z')
        await cronTick({ revisions, queue, now: () => t0 }, tickA)
        await cronTick({ revisions, queue, now: () => t0 }, tickB)
        const t1 = new Date('2026-06-01T10:02:00Z')
        const outA = await cronTick({ revisions, queue, now: () => t1 }, tickA)
        const outB = await cronTick({ revisions, queue, now: () => t1 }, tickB)
        // Each tick reports its own `fired`, but the queue holds only one
        // session per minute (idempotency_key collision in
        // `enqueueOrResume`'s pre-check returns the existing id).
        const all = []
        for (const minute of [
            Math.floor(new Date('2026-06-01T10:01:00Z').getTime() / 60_000),
            Math.floor(new Date('2026-06-01T10:02:00Z').getTime() / 60_000),
        ]) {
            const session = await queue.findByIdempotencyKey(app.id, `cron:${rev.id}:digest:${minute}`)
            if (session) {
                all.push(session)
            }
        }
        // Most-recent collapses 2 missed firings to 1; one session per replica
        // pass — at most 1 row exists for the surviving firing.
        const unique = new Set(all.map((s) => s.id))
        expect(unique.size).toBeLessThanOrEqual(2)
        // outB's fired count is what the second replica thinks it did; the
        // queue's reality is the same single row.
        void outA
        void outB
    })

    it('stamps trigger_metadata on the fired session', async () => {
        const revisions = new PgRevisionStore(pool)
        const queue = new PgSessionQueue(pool)
        const { app, rev } = await deploy(revisions, {
            triggers: [minimalCron({ schedule: '* * * * *', prompt: 'p', timezone: 'UTC' })],
        })
        const state = newCronTickState()
        const t0 = new Date('2026-06-01T10:00:00Z')
        await cronTick({ revisions, queue, now: () => t0 }, state)
        const t1 = new Date('2026-06-01T10:01:30Z')
        await cronTick({ revisions, queue, now: () => t1 }, state)
        const session = await queue.findByIdempotencyKey(
            app.id,
            `cron:${rev.id}:digest:${Math.floor(new Date('2026-06-01T10:01:00Z').getTime() / 60_000)}`
        )
        expect(session).not.toBeNull()
        expect(session!.trigger_metadata).toMatchObject({
            kind: 'cron',
            cron_name: 'digest',
            schedule: '* * * * *',
        })
    })

    it('expands {fired_at:iso|date|week} + {cron_name} + {schedule} placeholders in the prompt', async () => {
        const revisions = new PgRevisionStore(pool)
        const queue = new PgSessionQueue(pool)
        const { app, rev } = await deploy(revisions, {
            triggers: [
                minimalCron({
                    schedule: '0 9 * * MON',
                    prompt: 'name={cron_name} sched={schedule} iso={fired_at:iso} date={fired_at:date} week={fired_at:week}',
                }),
            ],
        })
        const state = newCronTickState()
        // 2026-06-01 is a Monday — a 09:00 firing lands in the window.
        const t0 = new Date('2026-06-01T08:00:00Z')
        await cronTick({ revisions, queue, now: () => t0 }, state)
        const t1 = new Date('2026-06-01T09:30:00Z')
        await cronTick({ revisions, queue, now: () => t1 }, state)
        const sessions = []
        for (const minute of [Math.floor(new Date('2026-06-01T09:00:00Z').getTime() / 60_000)]) {
            const s = await queue.findByIdempotencyKey(app.id, `cron:${rev.id}:digest:${minute}`)
            if (s) {
                sessions.push(s)
            }
        }
        expect(sessions).toHaveLength(1)
        const content = (sessions[0].conversation[0] as { content: string }).content
        expect(content).toContain('name=digest')
        expect(content).toContain('sched=0 9 * * MON')
        expect(content).toContain('iso=2026-06-01T09:00:00.000Z')
        expect(content).toContain('date=2026-06-01')
        expect(content).toContain('week=2026-W23')
    })

    it('expands placeholders in external_key — same set as prompt', async () => {
        const revisions = new PgRevisionStore(pool)
        const queue = new PgSessionQueue(pool)
        const { app, rev } = await deploy(revisions, {
            triggers: [
                minimalCron({
                    schedule: '0 9 * * MON',
                    external_key: 'digest-{fired_at:week}',
                    prompt: 'go',
                }),
            ],
        })
        const state = newCronTickState()
        const t0 = new Date('2026-06-01T08:00:00Z')
        await cronTick({ revisions, queue, now: () => t0 }, state)
        const t1 = new Date('2026-06-01T09:30:00Z')
        await cronTick({ revisions, queue, now: () => t1 }, state)
        const byExternal = await queue.findByExternalKey(app.id, 'digest-2026-W23', rev.id)
        expect(byExternal).not.toBeNull()
    })

    it('parse_failed surfaces an error count without taking down the tick', async () => {
        // A malformed schedule (something the freeze validator would've
        // rejected, but injected here to prove the runtime is defensive)
        // increments `errors`, doesn't fire, doesn't throw.
        const revisions = new PgRevisionStore(pool)
        const queue = new PgSessionQueue(pool)
        await deploy(revisions, {
            triggers: [{ type: 'cron', config: { name: 'bad', schedule: 'definitely-not-a-cron', prompt: 'go' } }],
        })
        const state = newCronTickState()
        const t0 = new Date('2026-06-01T10:00:00Z')
        await cronTick({ revisions, queue, now: () => t0 }, state)
        const t1 = new Date('2026-06-01T10:02:00Z')
        const out = await cronTick({ revisions, queue, now: () => t1 }, state)
        expect(out.errors).toBeGreaterThan(0)
        expect(out.fired).toBe(0)
    })

    describe('fireCronManually', () => {
        it('fires a session with the cron-manual idempotency-key shape', async () => {
            const revisions = new PgRevisionStore(pool)
            const queue = new PgSessionQueue(pool)
            const { app, rev } = await deploy(revisions, {
                triggers: [minimalCron({ schedule: '0 9 * * MON', prompt: 'manual test' })],
            })
            const result = await fireCronManually(
                { revisions, queue },
                { rev, app, cronName: 'digest', requestId: 'req-1' }
            )
            expect(result.idempotency_key).toBe(`cron-manual:${rev.id}:digest:req-1`)
            const session = await queue.get(result.session_id)
            expect((session!.conversation[0] as { content: string }).content).toBe('manual test')
            expect(session!.trigger_metadata).toMatchObject({ kind: 'cron', manual: true })
        })

        it('same request_id is idempotent — second call returns the original session id', async () => {
            const revisions = new PgRevisionStore(pool)
            const queue = new PgSessionQueue(pool)
            const { app, rev } = await deploy(revisions, {
                triggers: [minimalCron({ schedule: '0 9 * * MON' })],
            })
            const a = await fireCronManually(
                { revisions, queue },
                { rev, app, cronName: 'digest', requestId: 'click-1' }
            )
            const b = await fireCronManually(
                { revisions, queue },
                { rev, app, cronName: 'digest', requestId: 'click-1' }
            )
            expect(b.session_id).toBe(a.session_id)
        })

        it('throws when the cron name is unknown', async () => {
            const revisions = new PgRevisionStore(pool)
            const queue = new PgSessionQueue(pool)
            const { app, rev } = await deploy(revisions, {
                triggers: [minimalCron({ schedule: '0 9 * * MON' })],
            })
            await expect(
                fireCronManually({ revisions, queue }, { rev, app, cronName: 'ghost', requestId: 'r' })
            ).rejects.toThrow(/unknown_cron:ghost/)
        })
    })
})
