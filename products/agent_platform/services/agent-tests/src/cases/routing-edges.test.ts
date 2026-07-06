/**
 * Routing edges: the right surface is gated by the right trigger declaration.
 *
 * Old equivalent: isolated/routing-edges.test.ts.
 */

import request from 'supertest'

import { buildCluster, closeSharedPool, Cluster, fauxText } from '../harness'

describe('routing edges: real e2e', () => {
    let c: Cluster

    afterEach(async () => {
        if (c) {
            await c.teardown()
        }
    })

    afterAll(async () => {
        await closeSharedPool()
    })

    it('agent with only a slack trigger → POST /run → 404', async () => {
        c = await buildCluster()
        await c.deployAgent({
            slug: 'slack-only',
            spec: { triggers: [{ type: 'slack', config: { trusted_workspaces: '*' } }] },
        })
        const res = await request(c.ingress).post('/agents/slack-only/run').send({ message: 'x' })
        expect(res.status).toBe(404)
        expect(res.body.error).toBe('no_chat_trigger')
    })

    it('agent with only a chat trigger → POST /slack/events → 404', async () => {
        c = await buildCluster()
        await c.deployAgent({
            slug: 'chat-only',
            spec: {
                triggers: [
                    {
                        type: 'chat',
                        config: {},
                        auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] },
                    },
                ],
            },
        })
        const res = await request(c.ingress)
            .post('/agents/chat-only/slack/events')
            .send({
                type: 'event_callback',
                event: { type: 'message', channel: 'C01', user: 'U01', text: 'hi', ts: '1' },
            })
        expect(res.status).toBe(404)
        expect(res.body.error).toBe('no_slack_trigger')
    })

    it('agent with only a chat trigger → POST /webhook → 404', async () => {
        c = await buildCluster()
        await c.deployAgent({
            slug: 'no-webhook',
            spec: {
                triggers: [
                    {
                        type: 'chat',
                        config: {},
                        auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] },
                    },
                ],
            },
        })
        const res = await request(c.ingress).post('/agents/no-webhook/webhook').send({})
        expect(res.status).toBe(404)
        expect(res.body.error).toBe('no_webhook_trigger')
    })

    it('unknown slug (path mode) → 404', async () => {
        c = await buildCluster()
        const res = await request(c.ingress).post('/agents/ghost/run').send({ message: 'x' })
        expect(res.status).toBe(404)
    })

    it('unknown host (domain mode) → 404', async () => {
        c = await buildCluster({ routingMode: 'domain', domainSuffix: '.agents.posthog.test' })
        await c.deployAgent({ slug: 'real-one' })
        const res = await request(c.ingress)
            .post('/run')
            .set('host', 'ghost.agents.posthog.test')
            .send({ message: 'x' })
        expect(res.status).toBe(404)
    })

    it('host outside the configured domain suffix → 404', async () => {
        c = await buildCluster({ routingMode: 'domain', domainSuffix: '.agents.posthog.test' })
        await c.deployAgent({ slug: 'real-one' })
        const res = await request(c.ingress)
            .post('/run')
            .set('host', 'real-one.other-domain.com')
            .send({ message: 'x' })
        expect(res.status).toBe(404)
    })

    it('domain-mode happy path: host=<slug>.<suffix> routes to the agent', async () => {
        c = await buildCluster({ routingMode: 'domain', domainSuffix: '.agents.posthog.test' })
        c.setScript([fauxText('routed')])
        await c.deployAgent({ slug: 'domain-agent', spec: {} })
        const res = await request(c.ingress)
            .post('/run')
            .set('host', 'domain-agent.agents.posthog.test')
            .send({ message: 'hello' })
        expect(res.status).toBe(200)
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')
    })
})
