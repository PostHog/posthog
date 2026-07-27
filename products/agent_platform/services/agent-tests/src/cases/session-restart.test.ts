/**
 * Session restart + new state machine contract.
 *
 * Pins the wire-level behaviour of the redesign:
 *
 *   queued / running / completed (OPEN) / closed (TERMINAL) / failed (TERMINAL)
 *
 * - `completed` is no longer terminal — the agent finished its turn but the
 *   session is open for more `/send`s. This is the default end-of-turn state.
 * - `closed` is what `completed` used to be: sealed, /send returns 410
 *   unless the trigger's `allow_restart` flag re-opens it (state → queued).
 * - `waiting` is gone. There is no dedicated "ask for input" tool; the
 *   agent writes the question in its reply and ends the turn, landing
 *   at `completed` like any other turn end.
 *
 * Meta tools (always-on):
 *   - `meta-end-turn` — explicit "turn done, session open". Equivalent to
 *     natural stop. State → completed.
 *   - `meta-end-session` — explicit hard close. State → closed.
 *
 * These tests are written *before* the implementation lands — they fail
 * today against the old state machine and turn green once the redesign
 * ships.
 */

import request from 'supertest'

import { buildCluster, closeSharedPool, Cluster, fauxCallTool, fauxText } from '../harness'

describe('session restart + new state machine: real e2e', () => {
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

    // ─────────────────────────────────────────────────────────────
    // Case 1 — natural stop lands at `completed` (open). /send re-queues
    // the same session; runner picks it up, drains the new message into
    // conversation, the model produces a follow-up assistant turn.
    // ─────────────────────────────────────────────────────────────
    it('case 1: /send to a `completed` (open) session continues the same conversation', async () => {
        c.setScript([fauxText('hi back'), fauxText('still here')])
        await c.deployAgent({ slug: 'open-1' })

        const run = await request(c.ingress).post('/agents/open-1/run').send({ message: 'first' })
        expect(run.status).toBe(200)
        const sid = run.body.session_id
        await c.drain()

        // Agent ended its turn naturally → `completed`, but session is OPEN.
        let session = await c.queue.get(sid)
        expect(session!.state).toBe('completed')

        // Follow-up /send: NEW behavior — 200, re-queues the same session.
        const send = await request(c.ingress).post('/agents/open-1/send').send({ session_id: sid, message: 'second' })
        expect(send.status).toBe(200)

        await c.drain()
        session = await c.queue.get(sid)
        // Same session id, same logical conversation, runner produced
        // another assistant turn after seeing the new user message.
        expect(session!.state).toBe('completed')
        const userMsgs = session!.conversation.filter((m) => m.role === 'user')
        expect(userMsgs.map((m) => (typeof m.content === 'string' ? m.content : ''))).toEqual(['first', 'second'])
        const assistantTurns = session!.conversation.filter((m) => m.role === 'assistant')
        expect(assistantTurns).toHaveLength(2)
    })

    // ─────────────────────────────────────────────────────────────
    // Case 2 — `meta-end-session` is the explicit hard-close path. State
    // lands at `closed`, and the default trigger (no `allow_restart`)
    // refuses /send with 410.
    // ─────────────────────────────────────────────────────────────
    it('case 2: meta-end-session → closed; /send is 410 by default', async () => {
        c.setScript([fauxCallTool('@posthog/meta-end-session', { summary: 'all done' })])
        await c.deployAgent({ slug: 'closer-1' })

        const run = await request(c.ingress).post('/agents/closer-1/run').send({ message: 'wrap up' })
        const sid = run.body.session_id
        await c.drain()

        const session = await c.queue.get(sid)
        expect(session!.state).toBe('closed')

        const send = await request(c.ingress).post('/agents/closer-1/send').send({ session_id: sid, message: 'wait!' })
        expect(send.status).toBe(410)
        expect(send.body).toMatchObject({ error: 'session_terminal', state: 'closed' })
    })

    // ─────────────────────────────────────────────────────────────
    // Case 3 — `allow_restart` reopens a `closed` session. /send 200,
    // session state goes back to `queued`, runner drains the message
    // into the existing conversation.
    // ─────────────────────────────────────────────────────────────
    it('case 3: allow_restart=true on chat trigger reopens a closed session', async () => {
        c.setScript([fauxCallTool('@posthog/meta-end-session', { summary: 'done' }), fauxText('back from the dead')])
        await c.deployAgent({
            slug: 'closer-2',
            spec: {
                triggers: [
                    {
                        type: 'chat',
                        config: { allow_restart: true },
                        auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] },
                    },
                ],
            },
        })

        const run = await request(c.ingress).post('/agents/closer-2/run').send({ message: 'first' })
        const sid = run.body.session_id
        await c.drain()

        expect((await c.queue.get(sid))!.state).toBe('closed')

        const send = await request(c.ingress).post('/agents/closer-2/send').send({ session_id: sid, message: 'second' })
        expect(send.status).toBe(200)

        await c.drain()
        const session = await c.queue.get(sid)
        expect(session!.state).toBe('completed')
        const assistantTurns = session!.conversation.filter((m) => m.role === 'assistant')
        // Two assistant turns: the meta-end-session call + the post-restart text.
        expect(assistantTurns).toHaveLength(2)
        const finalText = (assistantTurns[1] as { content: Array<{ type: string; text?: string }> }).content[0].text
        expect(finalText).toBe('back from the dead')
    })

    // ─────────────────────────────────────────────────────────────
    // Case 4 — `failed` stays terminal regardless of `allow_restart`. A
    // failed session is an error state, not a closed one; restarting
    // would likely just re-fail.
    // ─────────────────────────────────────────────────────────────
    it('case 4: failed sessions stay terminal; /send is 410 even with allow_restart', async () => {
        c.setScript([fauxText('about to crash')])
        await c.deployAgent({
            slug: 'crasher',
            spec: {
                triggers: [
                    {
                        type: 'chat',
                        config: { allow_restart: true },
                        auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] },
                    },
                ],
                limits: { max_turns: 1, max_tool_calls: 10, max_wall_seconds: 60 },
            },
        })

        // Force a failure: max_turns: 1 + a tool call that needs a second turn.
        c.setScript([fauxCallTool('@posthog/query', { query: 'select 1' })])
        await c.deployAgent({
            slug: 'crasher-2',
            spec: {
                triggers: [
                    {
                        type: 'chat',
                        config: { allow_restart: true },
                        auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] },
                    },
                ],
                tools: [{ kind: 'native', id: '@posthog/query' }],
                limits: { max_turns: 1, max_tool_calls: 10, max_wall_seconds: 60 },
            },
        })

        const run = await request(c.ingress).post('/agents/crasher-2/run').send({ message: 'go' })
        const sid = run.body.session_id
        await c.drain()

        expect((await c.queue.get(sid))!.state).toBe('failed')

        const send = await request(c.ingress)
            .post('/agents/crasher-2/send')
            .send({ session_id: sid, message: 'try again' })
        expect(send.status).toBe(410)
        expect(send.body).toMatchObject({ error: 'session_terminal', state: 'failed' })
    })

    // ─────────────────────────────────────────────────────────────
    // Case 5 — `meta-end-turn` is the explicit equivalent of natural
    // stop. The session goes to `completed` (open), not `closed`.
    // ─────────────────────────────────────────────────────────────
    it('case 5: meta-end-turn → completed (open), not closed', async () => {
        c.setScript([fauxCallTool('@posthog/meta-end-turn', {})])
        await c.deployAgent({ slug: 'turner' })

        const run = await request(c.ingress).post('/agents/turner/run').send({ message: 'hi' })
        const sid = run.body.session_id
        await c.drain()

        expect((await c.queue.get(sid))!.state).toBe('completed')

        // And /send keeps working — same as a natural stop.
        c.setScript([fauxText('still around')])
        const send = await request(c.ingress).post('/agents/turner/send').send({ session_id: sid, message: 'more' })
        expect(send.status).toBe(200)
        await c.drain()
        expect((await c.queue.get(sid))!.state).toBe('completed')
    })

    // ─────────────────────────────────────────────────────────────
    // Case 6 — An agent that asks the user a question does so with
    // plain text and ends the turn. The session lands at `completed`
    // (open), /send drains the reply into the conversation, the model
    // continues from there.
    // ─────────────────────────────────────────────────────────────
    it('case 6: text-only follow-up → completed (open); no `waiting` state', async () => {
        c.setScript([fauxText("what's your name?"), fauxText('hello, alice')])
        await c.deployAgent({ slug: 'asker' })

        const run = await request(c.ingress).post('/agents/asker/run').send({ message: 'hi' })
        const sid = run.body.session_id
        await c.drain()

        // No more `waiting` — a text-only turn just lands at completed.
        let session = await c.queue.get(sid)
        expect(session!.state).toBe('completed')

        // The user replies and the session continues — no special wake
        // path needed because it was never parked.
        const send = await request(c.ingress).post('/agents/asker/send').send({ session_id: sid, message: 'alice' })
        expect(send.status).toBe(200)

        await c.drain()
        session = await c.queue.get(sid)
        expect(session!.state).toBe('completed')
        const assistantTurns = session!.conversation.filter((m) => m.role === 'assistant')
        expect(assistantTurns).toHaveLength(2)
        const finalText = (assistantTurns[1] as { content: Array<{ type: string; text?: string }> }).content[0].text
        expect(finalText).toBe('hello, alice')
    })
})
