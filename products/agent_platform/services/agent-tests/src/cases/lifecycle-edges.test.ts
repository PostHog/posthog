/**
 * Lifecycle edges on /send and /cancel.
 *
 * Old equivalent: persistent-chat/lifecycle-edges.test.ts.
 */

import request from 'supertest'

import { buildCluster, closeSharedPool, Cluster, fauxCallTool, fauxErrorTurn, fauxText } from '../harness'

describe('session lifecycle edges: real e2e', () => {
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

    it('/send to a closed session → 410 Gone (no allow_restart)', async () => {
        // Under the new state machine the only path to a "no-more-sends"
        // terminal is `closed` (via meta-end-session). Without
        // `allow_restart` on the chat trigger that 410s on /send.
        c.setScript([fauxCallTool('@posthog/meta-end-session', { summary: 'done' })])
        await c.deployAgent({ slug: 'lc1' })
        const create = await request(c.ingress).post('/agents/lc1/run').send({ message: 'first' })
        await c.drain()
        expect((await c.queue.get(create.body.session_id))!.state).toBe('closed')

        const send = await request(c.ingress)
            .post('/agents/lc1/send')
            .send({ session_id: create.body.session_id, message: 'second' })
        expect(send.status).toBe(410)
        expect(send.body.state).toBe('closed')
    })

    it('/send to a completed session is OK (200) — session is OPEN by default', async () => {
        // Under the new state machine `completed` is the open idle state.
        // /send re-queues and the runner picks up the new message.
        c.setScript([fauxText('done'), fauxText('still here')])
        await c.deployAgent({ slug: 'lc1b' })
        const create = await request(c.ingress).post('/agents/lc1b/run').send({ message: 'first' })
        await c.drain()
        expect((await c.queue.get(create.body.session_id))!.state).toBe('completed')

        const send = await request(c.ingress)
            .post('/agents/lc1b/send')
            .send({ session_id: create.body.session_id, message: 'second' })
        expect(send.status).toBe(200)
        await c.drain()
        const session = await c.queue.get(create.body.session_id)
        expect(session!.state).toBe('completed')
        expect(session!.conversation.filter((m) => m.role === 'assistant')).toHaveLength(2)
    })

    it('/send to a failed session → 410 Gone', async () => {
        c.setScript([fauxErrorTurn('boom')])
        await c.deployAgent({ slug: 'lc2' })
        const create = await request(c.ingress).post('/agents/lc2/run').send({ message: 'first' })
        await c.drain()
        expect((await c.queue.get(create.body.session_id))!.state).toBe('failed')
        const send = await request(c.ingress)
            .post('/agents/lc2/send')
            .send({ session_id: create.body.session_id, message: 'second' })
        expect(send.status).toBe(410)
    })

    it('/send to a nonexistent session id → 404', async () => {
        await c.deployAgent({ slug: 'lc3' })
        const res = await request(c.ingress)
            .post('/agents/lc3/send')
            .send({ session_id: '00000000-0000-0000-0000-000000000000', message: 'x' })
        expect(res.status).toBe(404)
    })

    it('/cancel of an idle `completed` (open) session → terminal cancelled', async () => {
        // `completed` is open by default, so /cancel is a real state
        // transition (the user wants out of this conversation). The
        // resulting state is `cancelled` (distinct from `failed`) so
        // operators can tell user-initiated termination from runtime
        // errors.
        c.setScript([fauxText('continue?')])
        await c.deployAgent({ slug: 'cc1' })
        const create = await request(c.ingress).post('/agents/cc1/run').send({ message: 'hi' })
        await c.drain()
        expect((await c.queue.get(create.body.session_id))!.state).toBe('completed')
        const cancel = await request(c.ingress).post('/agents/cc1/cancel').send({ session_id: create.body.session_id })
        expect(cancel.status).toBe(200)
        expect(cancel.body).toMatchObject({ ok: true, state: 'cancelled' })
        expect((await c.queue.get(create.body.session_id))!.state).toBe('cancelled')
    })

    it('/send to a cancelled session → 410 Gone with state=cancelled', async () => {
        c.setScript([fauxText('continue?')])
        await c.deployAgent({ slug: 'cc1b' })
        const create = await request(c.ingress).post('/agents/cc1b/run').send({ message: 'hi' })
        await c.drain()
        await request(c.ingress).post('/agents/cc1b/cancel').send({ session_id: create.body.session_id })
        const send = await request(c.ingress)
            .post('/agents/cc1b/send')
            .send({ session_id: create.body.session_id, message: 'second' })
        expect(send.status).toBe(410)
        expect(send.body).toMatchObject({ error: 'session_terminal', state: 'cancelled' })
    })

    it('/cancel of an already-cancelled session is idempotent', async () => {
        c.setScript([fauxText('continue?')])
        await c.deployAgent({ slug: 'cc1c' })
        const create = await request(c.ingress).post('/agents/cc1c/run').send({ message: 'hi' })
        await c.drain()
        await request(c.ingress).post('/agents/cc1c/cancel').send({ session_id: create.body.session_id })
        const second = await request(c.ingress).post('/agents/cc1c/cancel').send({ session_id: create.body.session_id })
        expect(second.status).toBe(200)
        expect(second.body).toMatchObject({ ok: true, idempotent: true, state: 'cancelled' })
    })

    it('/cancel of a terminal (closed) session is idempotent', async () => {
        c.setScript([fauxCallTool('@posthog/meta-end-session', { summary: 'done' })])
        await c.deployAgent({ slug: 'cc2' })
        const create = await request(c.ingress).post('/agents/cc2/run').send({ message: 'hi' })
        await c.drain()
        const cancel = await request(c.ingress).post('/agents/cc2/cancel').send({ session_id: create.body.session_id })
        expect(cancel.status).toBe(200)
        expect(cancel.body.idempotent).toBe(true)
        expect((await c.queue.get(create.body.session_id))!.state).toBe('closed')
    })

    it('/cancel of a nonexistent session → 404', async () => {
        await c.deployAgent({ slug: 'cc3' })
        const res = await request(c.ingress)
            .post('/agents/cc3/cancel')
            .send({ session_id: '00000000-0000-0000-0000-000000000000' })
        expect(res.status).toBe(404)
    })
})
