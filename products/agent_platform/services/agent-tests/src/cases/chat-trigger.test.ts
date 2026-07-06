/**
 * Chat trigger (`/run`, `/send`, `/listen`) e2e. Real ingress + runner + PG +
 * filesystem + PiAiClient. Model invocations route through pi-ai's faux
 * provider — `cluster.setScript([...])` arms responses for the next call(s).
 *
 * Covers the corresponding old test surface:
 *   - app: mock-anthropic SDK roundtrip (single-turn echo)
 *   - app: greeting-bot (asks for name, greets on second turn)
 *   - persistent-chat: basic-multi-turn
 *   - persistent-chat: lifecycle-edges (covered in lifecycle-edges.test.ts)
 */

import request from 'supertest'

import { buildCluster, closeSharedPool, Cluster, fauxText } from '../harness'

describe('chat trigger: real e2e', () => {
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

    it('single-turn echo: faux returns canned text, session completes', async () => {
        c.setScript([fauxText('hello world')])
        await c.deployAgent({ slug: 'echo' })
        const res = await request(c.ingress).post('/agents/echo/run').send({ message: 'hi' })
        expect(res.status).toBe(200)
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')
        const assistant = session!.conversation.find((m) => m.role === 'assistant')
        expect(assistant).not.toBeUndefined()
        const text = (assistant as { content: Array<{ type: string; text?: string }> }).content[0].text
        expect(text).toBe('hello world')
    })

    it('greeting-bot multi-turn: text question ends turn, /send continues, second turn completes', async () => {
        // Turn 1: the agent asks a question via plain text and ends the
        // turn (state=completed, open). Turn 2: a plain text reply after
        // the user's follow-up. There is no dedicated "ask for input"
        // tool — the model just writes the question and stops.
        c.setScript([fauxText("what's your name?"), fauxText('hello, alice')])
        await c.deployAgent({ slug: 'greeter' })
        const res = await request(c.ingress).post('/agents/greeter/run').send({ message: 'hi' })
        const sid = res.body.session_id
        await c.drain()
        let session = await c.queue.get(sid)
        expect(session!.state).toBe('completed')

        // User replies with their name.
        await request(c.ingress).post('/agents/greeter/send').send({ session_id: sid, message: 'alice' })
        await c.drain()
        session = await c.queue.get(sid)
        expect(session!.state).toBe('completed')

        const assistantTurns = session!.conversation.filter((m) => m.role === 'assistant')
        expect(assistantTurns).toHaveLength(2)
        const finalText = (assistantTurns[1] as { content: Array<{ type: string; text?: string }> }).content[0].text
        expect(finalText).toBe('hello, alice')
    })

    it('basic-multi-turn: /send to a `completed` (open) session re-queues; runner drains on resume', async () => {
        c.setScript([fauxText('continue?'), fauxText('ok done')])
        await c.deployAgent({ slug: 'multi' })
        const run = await request(c.ingress).post('/agents/multi/run').send({ message: 'first' })
        const sid = run.body.session_id
        await c.drain()
        // A text-only turn lands at `completed` (open). The runner went
        // idle; the follow-up /send wakes it.
        expect((await c.queue.get(sid))!.state).toBe('completed')

        const send = await request(c.ingress).post('/agents/multi/send').send({ session_id: sid, message: 'second' })
        expect(send.status).toBe(200)

        // /send routed into pending_inputs. Verify before drain.
        const before = await c.queue.get(sid)
        expect(before!.pending_inputs).toHaveLength(1)
        expect(before!.state).toBe('queued')

        await c.drain()
        const session = await c.queue.get(sid)
        expect(session!.state).toBe('completed')
        expect(session!.pending_inputs).toHaveLength(0) // drained
        const userMsgs = session!.conversation.filter((m) => m.role === 'user')
        const userTexts = userMsgs.map((m) => (typeof m.content === 'string' ? m.content : ''))
        expect(userTexts).toContain('first')
        expect(userTexts).toContain('second')
    })

    it('404s an unknown agent slug', async () => {
        const res = await request(c.ingress).post('/agents/ghost/run').send({ message: 'x' })
        expect(res.status).toBe(404)
    })

    it('404s an agent with no live revision (never 500)', async () => {
        // Create an application but skip the live-revision promotion so the
        // resolver returns null. The dock was 500-ing here because some
        // downstream path wasn't defensive; this asserts we surface the
        // missing-revision case as a clean 404.
        await c.revisions.createApplication({
            team_id: 1, // matches buildCluster's default teamId
            slug: 'pre-promotion',
            name: 'pre-promotion',
            description: '',
        })
        const res = await request(c.ingress).post('/agents/pre-promotion/run').send({ message: 'x' })
        expect(res.status).toBe(404)
        expect(res.body).toMatchObject({ error: 'no_agent' })
    })

    it('404s an agent whose live revision lacks a chat trigger (never 500)', async () => {
        // Deploy with an empty trigger list — `hasTrigger` should be
        // defensive about both missing trigger arrays and unmatched types.
        await c.deployAgent({ slug: 'no-chat', spec: { triggers: [{ type: 'webhook', config: { path: '/w' } }] } })
        const res = await request(c.ingress).post('/agents/no-chat/run').send({ message: 'x' })
        expect(res.status).toBe(404)
        expect(res.body).toMatchObject({ error: 'no_chat_trigger' })
    })

    it('stamps supported_client_tools from the /run body', async () => {
        c.setScript([fauxText('ok')])
        await c.deployAgent({ slug: 'supports' })
        const res = await request(c.ingress)
            .post('/agents/supports/run')
            .send({ message: 'hi', supported_client_tools: ['connect_mcp', 'set_secret'] })
        expect(res.status).toBe(200)
        const session = await c.queue.get(res.body.session_id)
        expect(session!.trigger_metadata).toEqual({
            kind: 'chat',
            supported_client_tools: ['connect_mcp', 'set_secret'],
        })
    })

    it('omits supported_client_tools when none are supplied', async () => {
        c.setScript([fauxText('ok')])
        await c.deployAgent({ slug: 'supports-none' })
        const res = await request(c.ingress).post('/agents/supports-none/run').send({ message: 'hi' })
        expect(res.status).toBe(200)
        const session = await c.queue.get(res.body.session_id)
        expect(session!.trigger_metadata).toEqual({ kind: 'chat' })
    })
})
