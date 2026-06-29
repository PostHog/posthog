/**
 * Webhook + per-agent MCP triggers.
 *
 * Old equivalent: webhook is new in v2 (was a generic public agent before),
 * MCP transport is new (per-agent MCP exposure).
 */

import { createHash } from 'node:crypto'
import request from 'supertest'

import { buildCluster, closeSharedPool, Cluster, fauxText } from '../harness'

function webhookKey(header: string, payload: unknown): string {
    const digest = createHash('sha256').update(JSON.stringify(payload)).digest('hex')
    return `webhook:${header}:${digest}`
}

describe('webhook trigger: real e2e', () => {
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

    it('creates a session with the JSON body as content', async () => {
        c.setScript([fauxText('ack')])
        await c.deployAgent({ slug: 'wh', spec: {} })
        const res = await request(c.ingress)
            .post('/agents/wh/webhook')
            .send({ payload: { account: 'acme' } })
        expect(res.status).toBe(200)
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')
        expect(session!.conversation[0].content).toBe(JSON.stringify({ payload: { account: 'acme' } }))
    })

    it('x-external-key header is used for dedupe', async () => {
        await c.deployAgent({ slug: 'wh2', spec: {} })
        const a = await request(c.ingress).post('/agents/wh2/webhook').set('x-external-key', 'k-1').send({ a: 1 })
        const b = await request(c.ingress).post('/agents/wh2/webhook').set('x-external-key', 'k-1').send({ a: 2 })
        // First creates fresh, second resumes (since first is still queued/running)
        expect(a.body.resumed).toBe(false)
        expect(b.body.resumed).toBe(true)
        expect(b.body.session_id).toBe(a.body.session_id)
    })

    it('404s an unknown agent slug', async () => {
        const res = await request(c.ingress).post('/agents/ghost/webhook').send({})
        expect(res.status).toBe(404)
    })

    it('Idempotency-Key header dedupes a webhook redelivery to one session', async () => {
        // Two POSTs with identical Idempotency-Key — the second is a
        // no-op that returns the original session id. Models the
        // Stripe / GitHub / Slack retry shape: the provider re-fires
        // a webhook because the first attempt timed out from its side,
        // even though we accepted it. Without the dedupe, the agent
        // would run twice for the same event.
        c.setScript([fauxText('ack')])
        await c.deployAgent({ slug: 'wh-idem', spec: {} })
        const key = 'evt_abc123'
        const a = await request(c.ingress)
            .post('/agents/wh-idem/webhook')
            .set('Idempotency-Key', key)
            .send({ amount: 100 })
        const b = await request(c.ingress)
            .post('/agents/wh-idem/webhook')
            .set('Idempotency-Key', key)
            .send({ amount: 100 })
        expect(a.body.session_id).toBe(b.body.session_id)
        // Both responses report `resumed: false` — the duplicate didn't
        // resume the original (it's the wrong semantic) and didn't
        // create a new row either.
        expect(a.body.resumed).toBe(false)
        expect(b.body.resumed).toBe(false)
        // The session row carries the namespaced key so an audit can
        // tell where the dedupe came from. Format is
        // `webhook:<header>:<sha256(payload)>` so a spoofed header with
        // a different body produces a different key (see the
        // spoofing-resistance case below).
        const session = await c.queue.get(a.body.session_id)
        expect(session!.idempotency_key).toBe(webhookKey(key, { amount: 100 }))
    })

    it('X-GitHub-Delivery header is the GitHub-shaped idempotency source', async () => {
        c.setScript([fauxText('ack')])
        await c.deployAgent({ slug: 'wh-gh', spec: {} })
        const delivery = '72d3162e-cc78-11e3-81ab-4c9367dc0958'
        const body = { action: 'opened' }
        const a = await request(c.ingress).post('/agents/wh-gh/webhook').set('X-GitHub-Delivery', delivery).send(body)
        const b = await request(c.ingress).post('/agents/wh-gh/webhook').set('X-GitHub-Delivery', delivery).send(body)
        expect(a.body.session_id).toBe(b.body.session_id)
        const session = await c.queue.get(a.body.session_id)
        expect(session!.idempotency_key).toBe(webhookKey(delivery, body))
    })

    it('a guessed Idempotency-Key cannot pre-empt a legitimate delivery with a different body', async () => {
        // Spoofing-resistance: an attacker with reach to a public
        // webhook posts first with a guessed provider key (e.g. a Stripe
        // event id surfaced via a log) and a fake body. The real
        // provider then delivers the same event id with the real body.
        // With payload-digest namespacing the two requests land on
        // different idempotency keys, so the legitimate delivery still
        // creates its own session instead of dedupe-resolving to the
        // attacker's. Provider signature verification (in the auth
        // provider) is the primary defence; this is defence-in-depth.
        c.setScript([fauxText('ack'), fauxText('ack')])
        await c.deployAgent({ slug: 'wh-spoof', spec: {} })
        const key = 'evt_shared'
        const attacker = await request(c.ingress)
            .post('/agents/wh-spoof/webhook')
            .set('Idempotency-Key', key)
            .send({ payload: 'attacker' })
        const legit = await request(c.ingress)
            .post('/agents/wh-spoof/webhook')
            .set('Idempotency-Key', key)
            .send({ payload: 'legit' })
        expect(attacker.body.session_id).not.toBe(legit.body.session_id)
        const attackerSession = await c.queue.get(attacker.body.session_id)
        const legitSession = await c.queue.get(legit.body.session_id)
        expect(attackerSession!.idempotency_key).toBe(webhookKey(key, { payload: 'attacker' }))
        expect(legitSession!.idempotency_key).toBe(webhookKey(key, { payload: 'legit' }))
    })
})

describe('per-agent MCP transport: real e2e', () => {
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

    it('initialize returns server info with slug + revision id', async () => {
        await c.deployAgent({ slug: 'mcp-bot' })
        const res = await request(c.ingress)
            .post('/agents/mcp-bot/mcp')
            .send({ jsonrpc: '2.0', id: 1, method: 'initialize' })
        expect(res.body.result.serverInfo.name).toBe('agent:mcp-bot')
        expect(res.body.result.serverInfo.version).not.toBeUndefined()
        expect(res.body.result.protocolVersion).not.toBeUndefined()
    })

    it("tools/list returns the agent's ask tool", async () => {
        await c.deployAgent({ slug: 'lst' })
        const res = await request(c.ingress)
            .post('/agents/lst/mcp')
            .send({ jsonrpc: '2.0', id: 1, method: 'tools/list' })
        expect(res.body.result.tools).toHaveLength(1)
        expect(res.body.result.tools[0].name).toBe('ask')
        expect(res.body.result.tools[0].inputSchema.required).toContain('message')
    })

    it('tools/call name=ask enqueues a session and returns its id', async () => {
        c.setScript([fauxText('mcp ack')])
        await c.deployAgent({ slug: 'callee', spec: {} })
        const res = await request(c.ingress)
            .post('/agents/callee/mcp')
            .send({
                jsonrpc: '2.0',
                id: 2,
                method: 'tools/call',
                params: { name: 'ask', arguments: { message: 'via mcp' } },
            })
        const text = res.body.result.content[0].text
        const parsed = JSON.parse(text) as { session_id: string }
        expect(parsed.session_id).not.toBeUndefined()
        await c.drain()
        const session = await c.queue.get(parsed.session_id)
        expect(session!.state).toBe('completed')
        expect(session!.conversation[0].content).toBe('via mcp')
    })

    it('tools/call with unknown tool returns JSON-RPC error', async () => {
        await c.deployAgent({ slug: 'ut' })
        const res = await request(c.ingress)
            .post('/agents/ut/mcp')
            .send({
                jsonrpc: '2.0',
                id: 3,
                method: 'tools/call',
                params: { name: 'nope', arguments: {} },
            })
        expect(res.body.error).not.toBeUndefined()
        expect(res.body.error.code).toBe(-32601)
    })

    it('unknown JSON-RPC method returns error', async () => {
        await c.deployAgent({ slug: 'uk' })
        const res = await request(c.ingress).post('/agents/uk/mcp').send({ jsonrpc: '2.0', id: 4, method: 'nope/here' })
        expect(res.body.error).not.toBeUndefined()
    })
})
