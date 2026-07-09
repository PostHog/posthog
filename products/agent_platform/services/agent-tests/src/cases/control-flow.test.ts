/**
 * Control-flow primitives after the session-restart redesign:
 *   - meta.end_turn         → completed (open)
 *   - meta.end_session      → closed (terminal unless `allow_restart`)
 *   - max_turns ceiling     → failed
 *   - upstream model error  → failed
 *
 * Asking the user a question is no longer a meta tool — the agent
 * just emits text and ends the turn. That path is covered by the
 * default natural-stop test below.
 */

import request from 'supertest'

import { buildCluster, closeSharedPool, Cluster, fauxCallTool, fauxErrorTurn, fauxText } from '../harness'

describe('control flow: real e2e', () => {
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

    it('a text turn that asks a question lands at completed (open)', async () => {
        // No dedicated "ask for input" tool — the agent just responds
        // with text and ends the turn naturally.
        c.setScript([fauxText('continue?')])
        await c.deployAgent({ slug: 'asker' })
        const res = await request(c.ingress).post('/agents/asker/run').send({ message: 'hi' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')
    })

    it('end_session hard-closes the session', async () => {
        c.setScript([fauxCallTool('@posthog/meta-end-session', { summary: 'all done' })])
        await c.deployAgent({ slug: 'ender' })
        const res = await request(c.ingress).post('/agents/ender/run').send({ message: 'wrap' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('closed')
    })

    it('a meta tool call echoed by its provider-safe name (posthog_meta-end-turn) dispatches the real tool', async () => {
        // Real models echo tool calls by the provider-safe name, not the
        // `@posthog/...` original. Pre-fix, providerSafeName turned the leading
        // `@` into a leading underscore (`_posthog_meta-end-turn`), so the
        // model's `posthog_meta-end-turn` missed the reverse map and dispatched
        // as "tool not found" — burning a turn every session before the model
        // self-corrected. Script the sanitized name the real model emits.
        c.setScript([fauxCallTool('posthog_meta-end-turn')])
        await c.deployAgent({ slug: 'meta-safe-name' })
        const res = await request(c.ingress).post('/agents/meta-safe-name/run').send({ message: 'done?' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        // end_turn → completed, with no errored / not-found tool result anywhere.
        expect(session!.state).toBe('completed')
        const hasErroredToolResult = (session!.conversation as Array<{ role: string; isError?: boolean }>).some(
            (m) => m.role === 'toolResult' && m.isError === true
        )
        expect(hasErroredToolResult).toBe(false)
        expect(JSON.stringify(session!.conversation)).not.toContain('not found')
    })

    it('max_turns ceiling marks the session failed', async () => {
        // Script 5 tool calls — but the agent's max_turns is 3.
        c.setScript(
            Array(5)
                .fill(null)
                .map(() => fauxCallTool('@posthog/query', { query: 'select 1' }))
        )
        await c.deployAgent({
            slug: 'loopy',
            spec: {
                tools: [{ kind: 'native', id: '@posthog/query' }],
                limits: { max_turns: 3, max_tool_calls: 100, max_wall_seconds: 60 },
            },
        })
        const res = await request(c.ingress).post('/agents/loopy/run').send({ message: 'go' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('failed')
    })

    it('upstream model error walks through to a failed session', async () => {
        c.setScript([fauxErrorTurn('rate_limit')])
        await c.deployAgent({ slug: 'boom' })
        const res = await request(c.ingress).post('/agents/boom/run').send({ message: 'x' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('failed')
    })
})
