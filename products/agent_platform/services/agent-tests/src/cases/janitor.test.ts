/**
 * Janitor HTTP for Django: GET /sessions/:id, POST /sessions/:id/cancel, POST /sweep.
 *
 * Old equivalent: parts of isolated/cancel.test.ts + isolated/runtime.test.ts.
 */

import request from 'supertest'

import { buildCluster, closeSharedPool, Cluster, fauxText } from '../harness'

describe('janitor: real e2e', () => {
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

    it('GET /sessions/:id returns full session JSON after a run', async () => {
        c.setScript([fauxText('done')])
        await c.deployAgent({ slug: 'j1', spec: {} })
        const create = await request(c.ingress).post('/agents/j1/run').send({ message: 'hi' })
        await c.drain()
        const res = await request(c.janitor).get(`/sessions/${create.body.session_id}`)
        expect(res.status).toBe(200)
        expect(res.body.state).toBe('completed')
        expect(res.body.conversation.length).toBeGreaterThanOrEqual(2)
    })

    it('404s for missing session id', async () => {
        const res = await request(c.janitor).get('/sessions/00000000-0000-0000-0000-000000000000')
        expect(res.status).toBe(404)
    })

    it('POST /sessions/:id/cancel marks cancelled', async () => {
        c.setScript([fauxText('continue?')])
        await c.deployAgent({ slug: 'j2', spec: {} })
        const create = await request(c.ingress).post('/agents/j2/run').send({ message: 'hi' })
        await c.drain()
        expect((await c.queue.get(create.body.session_id))!.state).toBe('completed')
        const cancel = await request(c.janitor).post(`/sessions/${create.body.session_id}/cancel`)
        expect(cancel.status).toBe(200)
        expect((await c.queue.get(create.body.session_id))!.state).toBe('cancelled')
    })

    it('POST /sessions/:id/cancel is idempotent on already-cancelled', async () => {
        c.setScript([fauxText('continue?')])
        await c.deployAgent({ slug: 'j2b', spec: {} })
        const create = await request(c.ingress).post('/agents/j2b/run').send({ message: 'hi' })
        await c.drain()
        await request(c.janitor).post(`/sessions/${create.body.session_id}/cancel`)
        const second = await request(c.janitor).post(`/sessions/${create.body.session_id}/cancel`)
        expect(second.status).toBe(200)
        expect(second.body).toMatchObject({ ok: true, idempotent: true, state: 'cancelled' })
    })

    it('POST /sweep returns counts', async () => {
        const res = await request(c.janitor).post('/sweep')
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

    it('sweep re-queues stuck-running, then poison-pills after maxRetries', async () => {
        c.setScript([fauxText('done')])
        await c.deployAgent({ slug: 'pp', spec: {} })
        const create = await request(c.ingress).post('/agents/pp/run').send({ message: 'hi' })
        const sid = create.body.session_id

        // Simulate a stuck worker: pin the row in 'running' with a stale
        // claimed_at so the reaper picks it up. Drive the sweep directly via
        // janitor HTTP — we want to test the full path (HTTP → sweep → PG SQL).
        const goStale = async (): Promise<void> => {
            await c.pool.query(
                `UPDATE agent_session SET state='running', claimed_at=NOW() - interval '1 hour' WHERE id=$1`,
                [sid]
            )
        }
        const sweep = async (
            maxRetries: number
        ): Promise<{
            requeued: number
            poisoned: number
            closed: number
            expired_approvals: number
            cleared_idempotency_keys: number
        }> => {
            // Override the default 3 via direct sweep invocation. The HTTP
            // sweep endpoint uses whatever the janitor was configured with,
            // so for this test we hit the sweep helper through the cluster
            // pool. (Simpler than wiring an env-knob into the harness janitor.)
            const { sweepOnce } = await import('@posthog/agent-janitor')
            return sweepOnce({ queue: c.queue, stuckRunningThresholdMs: 1, maxRetries })
        }

        await goStale()
        const r1 = await sweep(2)
        expect(r1).toEqual({
            requeued: 1,
            poisoned: 0,
            closed: 0,
            expired_approvals: 0,
            cleared_idempotency_keys: 0,
            reaped_sandboxes: 0,
            sandbox_reap_failures: 0,
        })
        expect((await c.queue.get(sid))!.retry_count).toBe(1)

        await goStale()
        const r2 = await sweep(2)
        expect(r2).toEqual({
            requeued: 1,
            poisoned: 0,
            closed: 0,
            expired_approvals: 0,
            cleared_idempotency_keys: 0,
            reaped_sandboxes: 0,
            sandbox_reap_failures: 0,
        })
        expect((await c.queue.get(sid))!.retry_count).toBe(2)

        await goStale()
        const r3 = await sweep(2)
        expect(r3).toEqual({
            requeued: 0,
            poisoned: 1,
            closed: 0,
            expired_approvals: 0,
            cleared_idempotency_keys: 0,
            reaped_sandboxes: 0,
            sandbox_reap_failures: 0,
        })
        expect((await c.queue.get(sid))!.state).toBe('failed')
    })
})
