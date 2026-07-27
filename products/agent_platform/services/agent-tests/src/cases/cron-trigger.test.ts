/**
 * Cron trigger: real e2e.
 *
 * Drives the real janitor's `cronTick` against the harness's real Postgres
 * queue + revision store + worker + faux pi-ai. Proves the load-bearing
 * customer flow:
 *
 *   cronTick → enqueueOrResume (with idempotency_key) → worker claims →
 *   runner streams faux model → session completes with `trigger_metadata`
 *   stamped.
 *
 * Cron tick state lives in this test rather than the harness — the
 * janitor's prod entrypoint owns the setInterval, the harness boots
 * the janitor app without timers (so other tests aren't side-effected
 * by a scheduler kicking in). Calling `cronTick()` directly is the
 * canonical "fire one tick" shape for tests.
 */

import request from 'supertest'

import { cronTick, fireCronManually, newCronTickState } from '@posthog/agent-janitor'

import { buildCluster, closeSharedPool, Cluster, fauxText } from '../harness'

describe('cron trigger: real e2e', () => {
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

    it('cronTick fires a session at the scheduled minute and the runner completes it', async () => {
        // Faux model: one text turn. The runner's loop terminates on
        // stopReason='stop' (the default for fauxText).
        c.setScript([fauxText('digest ready')])
        const { application, revision } = await c.deployAgent({
            slug: 'cron-digest',
            spec: {
                models: { mode: 'manual', models: [{ model: 'faux/test' }] },
                triggers: [
                    {
                        type: 'cron',
                        config: {
                            name: 'digest',
                            schedule: '* * * * *',
                            prompt: 'Produce the digest for {fired_at:date}.',
                            timezone: 'UTC',
                        },
                    },
                ],
            },
        })

        const state = newCronTickState()
        const deps = { revisions: c.revisions, queue: c.queue, encryption: c.encryption }
        // First tick seeds lastTickAt; no firings in (now, now].
        const t0 = new Date('2026-06-01T09:00:00Z')
        const r0 = await cronTick({ ...deps, now: () => t0 }, state)
        expect(r0.fired).toBe(0)

        // Second tick: window (09:00, 09:01:30] contains 09:01 — fires once
        // under catch_up=most_recent (the default).
        const t1 = new Date('2026-06-01T09:01:30Z')
        const r1 = await cronTick({ ...deps, now: () => t1 }, state)
        expect(r1.fired).toBe(1)
        expect(r1.errors).toBe(0)

        // Worker drains the just-enqueued session.
        await c.drain()

        // The session lands keyed by `cron:<rev>:<name>:<minute>`. The unique
        // index in the migration guarantees there's exactly one matching row.
        const minute = Math.floor(new Date('2026-06-01T09:01:00Z').getTime() / 60_000)
        const session = await c.queue.findByIdempotencyKey(application.id, `cron:${revision.id}:digest:${minute}`)
        expect(session).not.toBeNull()
        expect(session!.state).toBe('completed')

        // The seed message is the placeholder-expanded prompt.
        const seed = session!.conversation[0] as { role: string; content: string }
        expect(seed.role).toBe('user')
        expect(seed.content).toBe('Produce the digest for 2026-06-01.')

        // trigger_metadata carries the firing context for the UI badge +
        // observability. The runner doesn't modify it; what cronTick stamps
        // is what we read back.
        expect(session!.trigger_metadata).toMatchObject({
            kind: 'cron',
            cron_name: 'digest',
            schedule: '* * * * *',
            fired_at: '2026-06-01T09:01:00.000Z',
        })

        // Conversation has user + assistant; the model's text response landed.
        expect(session!.conversation).toHaveLength(2)
        const assistant = session!.conversation[1] as { role: string; content: Array<{ text?: string }> }
        expect(assistant.role).toBe('assistant')
        expect(assistant.content[0].text).toBe('digest ready')
    })

    it('manual fire endpoint shape — POST /revisions/:id/cron/fire enqueues + the runner completes', async () => {
        // Uses the janitor HTTP route directly. The endpoint isn't on the
        // ingress (it's an authoring-side surface), so we hit the janitor
        // app the harness exposes. Same code path the console UI will
        // call when an author clicks "Fire now."
        c.setScript([fauxText('manual ack')])
        const { application, revision } = await c.deployAgent({
            slug: 'cron-manual',
            spec: {
                models: { mode: 'manual', models: [{ model: 'faux/test' }] },
                triggers: [
                    {
                        type: 'cron',
                        config: {
                            name: 'on-demand',
                            schedule: '0 9 * * MON',
                            prompt: 'Run the on-demand job.',
                            timezone: 'UTC',
                        },
                    },
                ],
            },
        })

        const res = await request(c.janitor)
            .post(`/revisions/${revision.id}/cron/fire`)
            .send({ cron_name: 'on-demand', request_id: 'click-1' })
        expect(res.status).toBe(200)
        expect(res.body.ok).toBe(true)
        expect(res.body.idempotency_key).toBe(`cron-manual:${revision.id}:on-demand:click-1`)

        await c.drain()

        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')
        expect(session!.application_id).toBe(application.id)
        expect(session!.trigger_metadata).toMatchObject({
            kind: 'cron',
            cron_name: 'on-demand',
            manual: true,
        })
    })

    it('fireCronManually with the same request_id is idempotent end-to-end (returns the same session id)', async () => {
        // Two manual fires with the same request_id should resolve to the
        // same session — exercises the dedupe round-trip through real PG.
        c.setScript([fauxText('once')])
        const { revision } = await c.deployAgent({
            slug: 'cron-dedupe',
            spec: {
                models: { mode: 'manual', models: [{ model: 'faux/test' }] },
                triggers: [
                    {
                        type: 'cron',
                        config: { name: 'dedup-test', schedule: '0 9 * * MON', prompt: 'p' },
                    },
                ],
            },
        })
        const a = await request(c.janitor)
            .post(`/revisions/${revision.id}/cron/fire`)
            .send({ cron_name: 'dedup-test', request_id: 'same' })
        const b = await request(c.janitor)
            .post(`/revisions/${revision.id}/cron/fire`)
            .send({ cron_name: 'dedup-test', request_id: 'same' })
        expect(a.status).toBe(200)
        expect(b.status).toBe(200)
        expect(b.body.session_id).toBe(a.body.session_id)

        // Reference fireCronManually so the import isn't unused — the route
        // delegates to it, so this test exercises both layers.
        expect(typeof fireCronManually).toBe('function')
    })
})
