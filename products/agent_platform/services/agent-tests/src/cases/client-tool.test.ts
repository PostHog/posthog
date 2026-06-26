/**
 * Client-fulfilled tool dispatch: the agent declares `kind: "client"` in its
 * spec, the model emits a tool call, the runner publishes a
 * `client_tool_call` event on the bus and waits for a matching
 * `client_tool_result` event posted by the connecting client. This case
 * exercises both halves (happy path + timeout path) using the in-memory
 * bus directly — simulating the role the chat client + ingress
 * `/client_tool_result` endpoint play in production.
 */

import request from 'supertest'

import { buildCluster, closeSharedPool, Cluster, fauxCallTool, fauxText } from '../harness'

describe('client-fulfilled tool dispatch: real e2e', () => {
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

    it('round-trip: model call → SSE event → client posts result → model receives it', async () => {
        c.setScript([fauxCallTool('get_context', {}), fauxText('saw context')])
        await c.deployAgent({
            slug: 'concierge-like',
            spec: {
                tools: [
                    {
                        kind: 'client',
                        id: 'get_context',
                        description: 'Returns the host UI context',
                        args_schema: { type: 'object', properties: {}, additionalProperties: false },
                    },
                ],
            },
        })

        // Simulate the connecting client: subscribe to bus events; when a
        // client_tool_call lands for our tool id, publish the result back
        // on the same bus (which is exactly what the ingress
        // /client_tool_result endpoint does in production).
        const seenCalls: Array<{ tool_id: string; call_id: string }> = []
        const res = await request(c.ingress)
            .post('/agents/concierge-like/run')
            .send({ message: 'fetch context', supported_client_tools: ['get_context'] })
        const sessionId = res.body.session_id as string
        const unsub = c.bus.subscribe(sessionId, (e) => {
            if (e.kind !== 'client_tool_call') {
                return
            }
            const d = e.data as { call_id: string; tool_id: string }
            seenCalls.push({ tool_id: d.tool_id, call_id: d.call_id })
            void c.bus.publish({
                session_id: sessionId,
                kind: 'client_tool_result',
                data: { call_id: d.call_id, result: { page: 'agent', agent: { slug: 'x' } } },
                ts: new Date().toISOString(),
            })
        })

        await c.drain()
        unsub()

        const session = await c.queue.get(sessionId)
        expect(session!.state).toBe('completed')
        expect(seenCalls).toHaveLength(1)
        expect(seenCalls[0].tool_id).toBe('get_context')

        // The conversation should include the tool result returned by our
        // simulated client (not an error).
        const toolResult = session!.conversation.find((m) => m.role === 'toolResult') as
            | { role: 'toolResult'; content: Array<{ type: string; text?: string }> }
            | undefined
        expect(toolResult).toBeTruthy()
        const body = toolResult!.content.find((c) => c.type === 'text')?.text ?? ''
        expect(body).toContain('"agent"')
        expect(body).toContain('"slug":"x"')
    })

    it('timeout path: no client responds → model gets client_tool_timeout, recovers', async () => {
        c.setScript([fauxCallTool('focus', { kind: 'file', path: 'agent.md' }), fauxText('ok no panel')])
        await c.deployAgent({
            slug: 'no-client',
            spec: {
                tools: [
                    {
                        kind: 'client',
                        id: 'focus',
                        description: 'Navigate the host panel',
                        args_schema: { type: 'object', properties: { kind: { type: 'string' } }, required: ['kind'] },
                        timeout_ms: 200, // tight so the test doesn't hang
                    },
                ],
            },
        })
        const res = await request(c.ingress)
            .post('/agents/no-client/run')
            .send({ message: 'focus the file', supported_client_tools: ['focus'] })
        const sessionId = res.body.session_id as string
        await c.drain({ iterations: 100 })

        const session = await c.queue.get(sessionId)
        expect(session!.state).toBe('completed')
        const toolResult = session!.conversation.find((m) => m.role === 'toolResult') as
            | { role: 'toolResult'; isError?: boolean; content: Array<{ type: string; text?: string }> }
            | undefined
        expect(toolResult).toBeTruthy()
        // The dispatcher rejects with Error('client_tool_timeout'); the loop
        // surfaces the throw as an error tool_result whose content carries
        // the message.
        const body = toolResult!.content.find((c) => c.type === 'text')?.text ?? ''
        expect(body).toContain('client_tool_timeout')
    })

    it('emits client_tool_call SSE before publishing the result', async () => {
        // Order matters: any SSE consumer must see the call before the result.
        const events: string[] = []
        c.setScript([fauxCallTool('toast', { message: 'hi' }), fauxText('done')])
        await c.deployAgent({
            slug: 'order',
            spec: {
                tools: [
                    {
                        kind: 'client',
                        id: 'toast',
                        description: 'Surface a status notification',
                        args_schema: { type: 'object', properties: { message: { type: 'string' } } },
                    },
                ],
            },
        })
        const res = await request(c.ingress)
            .post('/agents/order/run')
            .send({ message: 'go', supported_client_tools: ['toast'] })
        const sessionId = res.body.session_id as string
        const unsub = c.bus.subscribe(sessionId, (e) => {
            if (e.kind === 'client_tool_call' || e.kind === 'client_tool_result') {
                events.push(e.kind)
            }
            if (e.kind === 'client_tool_call') {
                const d = e.data as { call_id: string }
                void c.bus.publish({
                    session_id: sessionId,
                    kind: 'client_tool_result',
                    data: { call_id: d.call_id, result: { shown: true } },
                    ts: new Date().toISOString(),
                })
            }
        })
        await c.drain()
        unsub()
        expect(events[0]).toBe('client_tool_call')
        expect(events).toContain('client_tool_result')
    })
})
