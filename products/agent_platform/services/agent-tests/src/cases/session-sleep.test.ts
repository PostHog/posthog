/**
 * Session sleep (`@posthog/meta-sleep`): the full park → wake lifecycle.
 *
 *   - sleep parks the session in `waiting` with wake_at/slept_at + accrues the
 *     cumulative-sleep counter
 *   - a `sleeping` SSE event fires for live consumers
 *   - duration is clamped to the single-sleep cap
 *   - the janitor timer (wakeReadyWaiting) re-queues an elapsed sleep; the
 *     resumed turn runs and the cumulative counter is preserved (timer wake
 *     does NOT reset it)
 *   - a /send wakes a slept session early AND resets the cumulative counter
 *   - the cumulative-sleep cap denies a sleep once the budget is exhausted, and
 *     clamps the final sleep to the remaining budget
 *
 * See docs/session-sleep.md.
 */

import request from 'supertest'

import { sweepOnce } from '@posthog/agent-janitor'
import type { SessionEvent } from '@posthog/agent-shared'
import { MAX_CUMULATIVE_SLEEP_MINUTES, MAX_SLEEP_MINUTES } from '@posthog/agent-tools'

import { buildCluster, closeSharedPool, Cluster, fauxCallTool, fauxText } from '../harness'

const SLEEP_SPEC = { tools: [{ kind: 'native' as const, id: '@posthog/meta-sleep' }] }

/** Whole minutes between slept_at and wake_at — the exact sleep the runner committed to. */
function sleptMinutes(session: { slept_at?: string | null; wake_at?: string | null }): number {
    return Math.round((Date.parse(session.wake_at!) - Date.parse(session.slept_at!)) / 60_000)
}

describe('session sleep: real e2e', () => {
    let c: Cluster

    beforeEach(async () => {
        c = await buildCluster()
    })

    afterEach(async () => {
        await c.teardown()
    })

    afterAll(async () => {
        await closeSharedPool()
    })

    it('meta-sleep parks the session in waiting with wake_at/slept_at and accrues the counter', async () => {
        c.setScript([fauxCallTool('@posthog/meta-sleep', { duration_minutes: 30 })])
        await c.deployAgent({ slug: 'sleeper', spec: SLEEP_SPEC })
        const run = await request(c.ingress).post('/agents/sleeper/run').send({ message: 'go' })
        await c.drain()

        const session = (await c.queue.get(run.body.session_id))!
        expect(session.state).toBe('waiting')
        expect(session.slept_at).toBeTruthy()
        expect(session.wake_at).toBeTruthy()
        expect(Date.parse(session.wake_at!)).toBeGreaterThan(Date.parse(session.slept_at!))
        expect(sleptMinutes(session)).toBe(30)
        expect(session.slept_total_minutes).toBe(30)
    })

    it('publishes a `sleeping` SSE event carrying wake_at + requested_minutes', async () => {
        c.setScript([fauxCallTool('@posthog/meta-sleep', { duration_minutes: 15, reason: 'backoff' })])
        await c.deployAgent({ slug: 'sleeper-sse', spec: SLEEP_SPEC })
        const run = await request(c.ingress).post('/agents/sleeper-sse/run').send({ message: 'go' })
        const sid = run.body.session_id

        const events: SessionEvent[] = []
        const unsubscribe = c.bus.subscribe(sid, (e) => events.push(e))
        await c.drain()
        unsubscribe()

        const sleeping = events.find((e) => e.kind === 'sleeping')
        expect(sleeping).not.toBeUndefined()
        expect(sleeping!.data.requested_minutes).toBe(15)
        expect(sleeping!.data.wake_at).toBeTruthy()
        expect(sleeping!.data.reason).toBe('backoff')
    })

    it('parks for the full single-sleep cap when requested', async () => {
        // The args schema bounds duration_minutes at [1, MAX_SLEEP_MINUTES], so
        // the boundary value is the largest a validated call can reach; the
        // runner's belt-and-suspenders clamp guards anything that slips past.
        c.setScript([fauxCallTool('@posthog/meta-sleep', { duration_minutes: MAX_SLEEP_MINUTES })])
        await c.deployAgent({ slug: 'greedy-sleeper', spec: SLEEP_SPEC })
        const run = await request(c.ingress).post('/agents/greedy-sleeper/run').send({ message: 'go' })
        await c.drain()

        const session = (await c.queue.get(run.body.session_id))!
        expect(session.state).toBe('waiting')
        expect(sleptMinutes(session)).toBe(MAX_SLEEP_MINUTES)
        expect(session.slept_total_minutes).toBe(MAX_SLEEP_MINUTES)
    })

    it('the janitor timer re-queues an elapsed sleep and the resumed turn runs (counter preserved)', async () => {
        c.setScript([fauxCallTool('@posthog/meta-sleep', { duration_minutes: 30 }), fauxText('awake now')])
        await c.deployAgent({ slug: 'timer-wake', spec: SLEEP_SPEC })
        const run = await request(c.ingress).post('/agents/timer-wake/run').send({ message: 'go' })
        const sid = run.body.session_id
        await c.drain()
        expect((await c.queue.get(sid))!.state).toBe('waiting')

        // Sweep as if the wake_at has elapsed — wakeReadyWaiting flips it to queued.
        const result = await sweepOnce({ queue: c.queue, now: () => new Date(Date.now() + 31 * 60_000) })
        expect(result.woken).toBe(1)
        expect((await c.queue.get(sid))!.state).toBe('queued')

        // The runner re-claims it; the resume notice is injected and the next
        // scripted turn ends the session.
        await c.drain()
        const resumed = (await c.queue.get(sid))!
        expect(resumed.state).toBe('completed')
        // Timer wake does NOT reset the cumulative counter — only fresh external input does.
        expect(resumed.slept_total_minutes).toBe(30)
    })

    it('a /send wakes a slept session early and resets the cumulative counter', async () => {
        c.setScript([fauxCallTool('@posthog/meta-sleep', { duration_minutes: 45 }), fauxText('woken by message')])
        await c.deployAgent({ slug: 'early-wake', spec: SLEEP_SPEC })
        const run = await request(c.ingress).post('/agents/early-wake/run').send({ message: 'go' })
        const sid = run.body.session_id
        await c.drain()
        expect((await c.queue.get(sid))!.state).toBe('waiting')
        expect((await c.queue.get(sid))!.slept_total_minutes).toBe(45)

        // No sweep — an inbound message resumes it immediately via the /send path.
        await request(c.ingress).post('/agents/early-wake/send').send({ session_id: sid, message: 'wake up' })
        expect((await c.queue.get(sid))!.state).toBe('queued')
        await c.drain()

        const resumed = (await c.queue.get(sid))!
        expect(resumed.state).toBe('completed')
        // External input resets the budget so an interactive agent never hits the cap.
        expect(resumed.slept_total_minutes).toBe(0)
    })

    it('denies a sleep once the cumulative budget is exhausted (session continues, not parked)', async () => {
        c.setScript([fauxCallTool('@posthog/meta-sleep', { duration_minutes: 30 }), fauxText('continuing instead')])
        await c.deployAgent({ slug: 'capped-sleeper', spec: SLEEP_SPEC })
        const run = await request(c.ingress).post('/agents/capped-sleeper/run').send({ message: 'go' })
        const sid = run.body.session_id
        // Pin the cumulative counter at the cap before the worker claims it.
        await c.queue.update(sid, { slept_total_minutes: MAX_CUMULATIVE_SLEEP_MINUTES })
        await c.drain()

        const session = (await c.queue.get(sid))!
        // The sleep was refused (non-terminating result), so the loop ran the next
        // scripted turn and ended normally — it did NOT park in waiting.
        expect(session.state).toBe('completed')
        expect(session.wake_at).toBeNull()
        expect(session.slept_total_minutes).toBe(MAX_CUMULATIVE_SLEEP_MINUTES)
        const denied = JSON.stringify(session.conversation)
        expect(denied).toContain('cumulative_sleep_budget_exhausted')
    })

    it('clamps the final sleep to the remaining budget', async () => {
        c.setScript([fauxCallTool('@posthog/meta-sleep', { duration_minutes: MAX_SLEEP_MINUTES })])
        await c.deployAgent({ slug: 'budget-edge', spec: SLEEP_SPEC })
        const run = await request(c.ingress).post('/agents/budget-edge/run').send({ message: 'go' })
        const sid = run.body.session_id
        // Leave only 10 minutes of budget — less than a full single sleep.
        await c.queue.update(sid, { slept_total_minutes: MAX_CUMULATIVE_SLEEP_MINUTES - 10 })
        await c.drain()

        const session = (await c.queue.get(sid))!
        expect(session.state).toBe('waiting')
        expect(sleptMinutes(session)).toBe(10)
        expect(session.slept_total_minutes).toBe(MAX_CUMULATIVE_SLEEP_MINUTES)
    })
})
