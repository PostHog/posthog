/**
 * Queued follow-ups: /send calls that arrive while a session is parked or
 * in flight buffer to `pending_inputs` in arrival order. The runner drains
 * them into `conversation` at the start of the next turn.
 *
 * Old equivalent: persistent-chat/queued-followups.test.ts.
 */

import request from 'supertest'

import type { SessionEvent } from '@posthog/agent-shared'

import { buildCluster, closeSharedPool, Cluster, fauxText } from '../harness'

describe('queued follow-ups: real e2e', () => {
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

    it('a single /send after a text turn lands in pending_inputs', async () => {
        c.setScript([fauxText('go?'), fauxText('ok')])
        await c.deployAgent({ slug: 'q1' })
        const run = await request(c.ingress).post('/agents/q1/run').send({ message: 'hi' })
        const sid = run.body.session_id
        await c.drain()
        // A text-only turn lands at `completed` (open).
        expect((await c.queue.get(sid))!.state).toBe('completed')

        await request(c.ingress).post('/agents/q1/send').send({ session_id: sid, message: 'first follow-up' })
        const session = await c.queue.get(sid)
        expect(session!.pending_inputs).toHaveLength(1)
        expect(session!.pending_inputs[0].content).toBe('first follow-up')
    })

    it('three /sends after a completed turn buffer in arrival order; drain preserves order', async () => {
        c.setScript([fauxText('go?'), fauxText('done')])
        await c.deployAgent({ slug: 'q3' })
        const run = await request(c.ingress).post('/agents/q3/run').send({ message: 'first' })
        const sid = run.body.session_id
        await c.drain()
        // A text-only turn lands at `completed` (open).
        expect((await c.queue.get(sid))!.state).toBe('completed')

        // Three /sends without draining between them.
        await request(c.ingress).post('/agents/q3/send').send({ session_id: sid, message: 'second' })
        await request(c.ingress).post('/agents/q3/send').send({ session_id: sid, message: 'third' })
        await request(c.ingress).post('/agents/q3/send').send({ session_id: sid, message: 'fourth' })

        // All three queued, in order.
        const before = await c.queue.get(sid)
        expect(before!.pending_inputs.map((m) => (typeof m.content === 'string' ? m.content : ''))).toEqual([
            'second',
            'third',
            'fourth',
        ])

        await c.drain()
        const after = await c.queue.get(sid)
        expect(after!.state).toBe('completed')
        expect(after!.pending_inputs).toHaveLength(0)

        const userTexts = after!.conversation
            .filter((m) => m.role === 'user')
            .map((m) => (typeof m.content === 'string' ? m.content : ''))
        // The drained user messages appear in arrival order, after the original.
        expect(userTexts).toEqual(['first', 'second', 'third', 'fourth'])
    })

    it('a /send issued while the worker is mid-turn is drained at the next turn', async () => {
        await c.deployAgent({ slug: 'q-mid' })
        const run = await request(c.ingress).post('/agents/q-mid/run').send({ message: 'first' })
        const sid = run.body.session_id

        let sendDone: Promise<{ ok: boolean }> | null = null
        c.setScript([
            () => {
                // Inside the faux turn — the worker has the session row
                // claimed and pi-ai is composing the assistant response.
                // Fire `/send` without awaiting: it queues onto the
                // event loop and races against the rest of runOne.
                sendDone = new Promise<{ ok: boolean }>((resolve) => {
                    request(c.ingress)
                        .post('/agents/q-mid/send')
                        .send({ session_id: sid, message: 'mid-turn-followup' })
                        .then((r) => resolve(r.body as { ok: boolean }))
                        .catch(() => resolve({ ok: false }))
                })
                return fauxText('first turn done')
            },
            fauxText('second turn drained'),
        ])

        // First drain runs turn 1 and triggers the mid-turn /send.
        await c.drain()
        // Make sure the /send completed before we drain again, so the
        // pending_input is durably written before turn 2 picks it up.
        const sendResult = await sendDone!
        expect(sendResult.ok).toBe(true)
        // Second drain claims the re-queued session and runs turn 2.
        await c.drain()

        const after = await c.queue.get(sid)
        expect(after!.state).toBe('completed')
        expect(after!.pending_inputs).toHaveLength(0)
        const userTexts = after!.conversation
            .filter((m) => m.role === 'user')
            .map((m) => (typeof m.content === 'string' ? m.content : ''))
        // The mid-turn follow-up landed in the conversation between the
        // two assistant turns — proves it was drained, not dropped.
        expect(userTexts).toEqual(['first', 'mid-turn-followup'])
    })

    it('emits user_message via SSE when a mid-turn /send is drained at the next turn', async () => {
        // Mirrors the previous test but asserts the live-stream side:
        // the SSE bus carries `user_message` for the drained follow-up
        // so connected chat UIs can swap their pending optimistic
        // bubble for the server-confirmed one.
        await c.deployAgent({ slug: 'q-mid-sse' })
        const run = await request(c.ingress).post('/agents/q-mid-sse/run').send({ message: 'first' })
        const sid = run.body.session_id

        let sendDone: Promise<void> | null = null
        c.setScript([
            () => {
                sendDone = new Promise<void>((resolve) => {
                    request(c.ingress)
                        .post('/agents/q-mid-sse/send')
                        .send({ session_id: sid, message: 'follow' })
                        .then(() => resolve())
                        .catch(() => resolve())
                })
                return fauxText('one')
            },
            fauxText('two'),
        ])

        const events: SessionEvent[] = []
        const unsubscribe = c.bus.subscribe(sid, (e) => events.push(e))
        // `subscribe()` fires the Redis SUBSCRIBE off without awaiting it;
        // wait for the channel to be live before draining, else the
        // `user_message` published mid-drain races the ACK and gets dropped.
        await c.bus.whenSubscribed(sid)

        await c.drain()
        await sendDone!
        await c.drain()
        unsubscribe()

        const userMessageEvts = events.filter((e) => e.kind === 'user_message')
        expect(userMessageEvts.map((e) => e.data.text)).toEqual(['follow'])
    })

    it('a /send BEFORE the worker dequeues is durable (lands in conversation, not lost)', async () => {
        // The fresh first-turn run never drains before /send fires; the
        // scripted text response ends the first turn cleanly.
        c.setScript([fauxText('?'), fauxText('done')])
        await c.deployAgent({ slug: 'q-early' })
        const run = await request(c.ingress).post('/agents/q-early/run').send({ message: 'first' })
        const sid = run.body.session_id

        // /send arrives while session is still queued (no drain yet).
        await request(c.ingress).post('/agents/q-early/send').send({ session_id: sid, message: 'early-second' })

        // Session is still 'queued', second message is in pending_inputs.
        const before = await c.queue.get(sid)
        expect(before!.state).toBe('queued')
        expect(before!.pending_inputs).toHaveLength(1)

        await c.drain()
        const after = await c.queue.get(sid)
        const userTexts = after!.conversation
            .filter((m) => m.role === 'user')
            .map((m) => (typeof m.content === 'string' ? m.content : ''))
        // Both messages present in order — neither dropped.
        expect(userTexts).toContain('first')
        expect(userTexts).toContain('early-second')
    })
})
