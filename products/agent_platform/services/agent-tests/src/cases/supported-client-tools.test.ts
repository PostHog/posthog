/**
 * `supported_client_tools` gating: the /run caller declares which `kind:'client'`
 * tool ids it can fulfil; the runner exposes only those to the model. A
 * `required` client tool the caller can't fulfil fails chat session open;
 * non-chat triggers (webhook/slack/cron/mcp) have no client to declare
 * support, so every client tool is hidden there and the model degrades.
 */

import request from 'supertest'

import { buildCluster, closeSharedPool, Cluster, fauxCallTool, fauxText } from '../harness'

interface ClientToolSpec {
    kind: 'client'
    id: string
    description: string
    args_schema: Record<string, unknown>
    required: boolean
}

const clientTool = (id: string, required = false): ClientToolSpec => ({
    kind: 'client',
    id,
    description: `client tool ${id}`,
    args_schema: { type: 'object', properties: {}, additionalProperties: false },
    required,
})

describe('supported_client_tools: capability-gated exposure', () => {
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

    it('exposes a declared client tool to the model and round-trips it; stores the declaration', async () => {
        c.setScript([fauxCallTool('get_context', {}), fauxText('saw context')])
        await c.deployAgent({
            slug: 'gated-supported',
            spec: { tools: [clientTool('get_context'), clientTool('focus')] },
        })
        const res = await request(c.ingress)
            .post('/agents/gated-supported/run')
            .send({ message: 'go', supported_client_tools: ['get_context'] })
        const sessionId = res.body.session_id as string

        // Stored on the session row exactly as declared (typed `chat` variant).
        const stored = await c.queue.get(sessionId)
        expect(stored!.trigger_metadata).toEqual({ kind: 'chat', supported_client_tools: ['get_context'] })

        const seen: string[] = []
        const unsub = c.bus.subscribe(sessionId, (e) => {
            if (e.kind !== 'client_tool_call') {
                return
            }
            const d = e.data as { call_id: string; tool_id: string }
            seen.push(d.tool_id)
            void c.bus.publish({
                session_id: sessionId,
                kind: 'client_tool_result',
                data: { call_id: d.call_id, result: { ok: true } },
                ts: new Date().toISOString(),
            })
        })
        await c.drain()
        unsub()

        const session = await c.queue.get(sessionId)
        expect(session!.state).toBe('completed')
        // The runner exposed get_context (model called it, runner dispatched it).
        expect(seen).toEqual(['get_context'])
        const toolResult = session!.conversation.find((m) => m.role === 'toolResult')
        expect(toolResult).toBeTruthy()
    })

    it('hides a non-required client tool the caller did not declare', async () => {
        // Model tries to call `focus`, which the caller did not declare → it was
        // never exposed, so the runner never dispatches it (no client_tool_call).
        c.setScript([fauxCallTool('focus', {}), fauxText('no panel')])
        await c.deployAgent({
            slug: 'gated-hidden',
            spec: { tools: [clientTool('get_context'), clientTool('focus')] },
        })
        const res = await request(c.ingress)
            .post('/agents/gated-hidden/run')
            .send({ message: 'focus please', supported_client_tools: ['get_context'] })
        const sessionId = res.body.session_id as string

        const seen: string[] = []
        const unsub = c.bus.subscribe(sessionId, (e) => {
            if (e.kind === 'client_tool_call') {
                seen.push((e.data as { tool_id: string }).tool_id)
            }
        })
        await c.drain({ iterations: 100 })
        unsub()

        expect(seen).not.toContain('focus')
        // Undeclared tool is silently skipped, not a session failure: the model
        // gets an unknown-tool error result and continues to its next turn.
        const session = await c.queue.get(sessionId)
        expect(session!.state).toBe('completed')
    })

    it('fails session open when a required client tool is not declared', async () => {
        c.setScript([fauxText('never runs')])
        await c.deployAgent({
            slug: 'gated-required',
            spec: { tools: [clientTool('connect_mcp', true)] },
        })
        const res = await request(c.ingress)
            .post('/agents/gated-required/run')
            .send({ message: 'go', supported_client_tools: [] })
        const sessionId = res.body.session_id as string
        await c.drain({ iterations: 100 })

        const session = await c.queue.get(sessionId)
        expect(session!.state).toBe('failed')
    })

    // Non-chat triggers have no connecting client to declare capabilities, so
    // every `kind:'client'` tool — required or not — is hidden and the model
    // degrades per agent.md. The `required` check fires only when there's
    // actually a client to disappoint (chat triggers); webhook/slack/cron/mcp
    // sessions never throw `client_tool_unsupported`.
    it('webhook session degrades silently when the spec has a required client tool', async () => {
        c.setScript([fauxText('handled the webhook')])
        await c.deployAgent({
            slug: 'webhook-required-client',
            spec: { tools: [clientTool('connect_mcp', true)] },
        })
        const res = await request(c.ingress).post('/agents/webhook-required-client/webhook').send({ alert: 'fired' })
        expect(res.status).toBe(200)
        await c.drain({ iterations: 100 })

        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')
        expect(session!.trigger_metadata).toEqual({ kind: 'webhook' })
    })
})
