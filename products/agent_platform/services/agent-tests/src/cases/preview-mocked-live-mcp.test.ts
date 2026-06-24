/**
 * Mocked ("preview") run against the LIVE revision, with real MCP access.
 *
 * This is the end-to-end proof of the mocked-run model the Agent Builder
 * relies on: a session that talks to an MCP server (the same shape the
 * builder uses for the PostHog MCP) can be driven entirely for real — real
 * ingress routing, real worker loop, real MCP transport, real tool dispatch —
 * with ONLY ONE thing faked: the preview JWT is minted in-process with the dev
 * signing key instead of via Django's `/preview-token` endpoint. Everything
 * downstream of that token is the production code path.
 *
 * What it pins:
 *   - A valid preview token attached to the LIVE revision's normal URL flips
 *     the run into mocked mode (`is_preview = true`) — no draft required. This
 *     is the "safely test / reproduce the live agent" capability.
 *   - SAFE (read-only, `readOnlyHint: true`) MCP tools execute for real: the
 *     in-process MCP server actually receives the call and returns live data.
 *   - DESTRUCTIVE (non-read-only) MCP tools are mocked: the server NEVER
 *     receives the call, and the model gets a synthetic `preview_skipped`
 *     result so it keeps reasoning.
 *   - Every `$ai_*` event is tagged `$agent_is_preview: true`.
 *   - Contrast guard: the SAME live revision with NO token is a real run —
 *     the destructive tool actually fires.
 *
 * The harness wires `internalSigningKey: DEV_INTERNAL_SIGNING_KEY` into the
 * ingress (see cluster.ts), so the gate verifies the token for real; the only
 * mock is who minted it.
 */

import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js'
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import type { Transport } from '@modelcontextprotocol/sdk/shared/transport.js'
import request from 'supertest'
import { z } from 'zod'

import type { McpTransportFactory } from '@posthog/agent-runner'
import { DEV_INTERNAL_SIGNING_KEY, INTERNAL_JWT_AUDIENCE, mintInternalJwt } from '@posthog/agent-shared'

import { buildCluster, closeSharedPool, Cluster, fauxCallTool, fauxText } from '../harness'

interface AnnotatedTool {
    description: string
    inputSchema?: Record<string, z.ZodTypeAny>
    /** MCP annotations the server advertises. `readOnlyHint: true` is what the
     *  runner gates a mocked run on. */
    annotations?: { readOnlyHint?: boolean; destructiveHint?: boolean }
    handler: (args: Record<string, unknown>) => unknown
}

/**
 * Transport factory backed by a fresh in-process `McpServer` per
 * `Client.connect`, exercising the real MCP protocol with no HTTP. `captured`
 * records every tool the server's handler ACTUALLY ran — the centrepiece
 * assertion is that a mocked run's destructive tool never lands here.
 */
function buildFactory(tools: Record<string, AnnotatedTool>): {
    factory: McpTransportFactory
    captured: Array<{ name: string; args: Record<string, unknown> }>
} {
    const captured: Array<{ name: string; args: Record<string, unknown> }> = []
    const factory: McpTransportFactory = (target): Transport => {
        const server = new McpServer({ name: 'harness-posthog-mcp', version: '1.0.0' })
        for (const [name, def] of Object.entries(tools)) {
            server.registerTool(
                name,
                {
                    title: name,
                    description: def.description,
                    inputSchema: def.inputSchema ?? {},
                    ...(def.annotations ? { annotations: def.annotations } : {}),
                },
                (args) => {
                    captured.push({ name, args: args as Record<string, unknown> })
                    return { content: [{ type: 'text' as const, text: JSON.stringify(def.handler(args)) }] }
                }
            )
        }
        void target
        const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair()
        void server.server.connect(serverTransport)
        return clientTransport
    }
    return { factory, captured }
}

/** A read-only tool the mocked run should RUN for real, and a destructive one
 *  it should suppress. Returned fresh per test so `captured` is isolated. */
function posthogLikeTools(): Record<string, AnnotatedTool> {
    return {
        list_dashboards: {
            description: 'List dashboards in the project. Read-only.',
            annotations: { readOnlyHint: true },
            handler: () => ({ dashboards: [{ id: 1, name: 'Revenue HQ' }] }),
        },
        delete_dashboard: {
            description: 'Delete a dashboard. Destructive.',
            inputSchema: { id: z.number() },
            annotations: { readOnlyHint: false, destructiveHint: true },
            handler: ({ id }) => ({ deleted: true, id }),
        },
    }
}

/** Pull the text out of a toolResult message (content is string | array). */
function toolResultText(msg: { content: string | Array<{ type: string; text?: string }> }): string {
    return Array.isArray(msg.content) ? (msg.content[0]?.text ?? '') : msg.content
}

describe('preview/mocked run against the LIVE revision, with real MCP', () => {
    let c: Cluster

    afterEach(async () => {
        await c?.teardown()
    })

    afterAll(async () => {
        await closeSharedPool()
    })

    it('mocked live run: read-only MCP tool runs for real, destructive one is suppressed', async () => {
        const { factory, captured } = buildFactory(posthogLikeTools())
        c = await buildCluster({ mcpTransportFactory: factory })
        // The agent reads (allowed), then tries to delete (must be mocked).
        c.setScript([
            fauxCallTool('ph__list_dashboards', {}),
            fauxCallTool('ph__delete_dashboard', { id: 1 }),
            fauxText('done'),
        ])

        // deployAgent freezes + promotes, so this revision IS the live one.
        const { application, revision } = await c.deployAgent({
            slug: 'mocked-live-mcp',
            spec: { mcps: [{ id: 'ph', url: 'https://example.com/ph' }] },
        })

        // The ONLY mocked part: mint the preview token in-process (stands in
        // for Django's POST /preview-token) bound to the LIVE revision.
        const token = await mintInternalJwt({
            audience: INTERNAL_JWT_AUDIENCE.INGRESS_PREVIEW,
            signingKey: DEV_INTERNAL_SIGNING_KEY,
            claims: { app: application.id, rev: revision.id },
            ttlSec: 900,
        })

        // Hit the live agent at its NORMAL url + the token → mocked run.
        const res = await request(c.ingress)
            .post('/agents/mocked-live-mcp/run')
            .set('x-agent-preview-token', token)
            .send({ message: 'tidy up the dashboards' })
        expect(res.status).toBe(200)

        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session).not.toBeNull()
        expect(session!.state).toBe('completed')
        // Mocked run, against the LIVE revision (no draft involved).
        expect(session!.is_preview).toBe(true)
        expect(session!.revision_id).toBe(revision.id)

        // Ground truth: the MCP server actually ran the read, and NEVER the
        // destructive call — the suppression happened before dispatch.
        const ranToolNames = captured.map((c) => c.name)
        expect(ranToolNames).toContain('list_dashboards')
        expect(ranToolNames).not.toContain('delete_dashboard')

        // The model saw real read data, and a synthetic skip for the write.
        const toolResults = session!.conversation.filter((m) => m.role === 'toolResult') as Array<{
            role: 'toolResult'
            isError: boolean
            content: string | Array<{ type: string; text?: string }>
        }>
        expect(toolResults).toHaveLength(2)
        const readText = toolResults.map(toolResultText).find((t) => t.includes('Revenue HQ'))
        const writeText = toolResults.map(toolResultText).find((t) => t.includes('preview_skipped'))
        expect(readText, 'read-only tool result should carry real data').toBeTruthy()
        expect(writeText, 'destructive tool result should be a preview_skipped synthetic').toBeTruthy()
        // Neither surfaced as an error — the suppressed write looks like a
        // successful no-op to the model so it keeps going.
        expect(toolResults.every((t) => t.isError === false)).toBe(true)

        // Author-iteration marker on every emitted analytics event.
        const entries = c.analytics.forSession(res.body.session_id)
        expect(entries.length).toBeGreaterThan(0)
        for (const e of entries) {
            expect(e.event.is_preview).toBe(true)
            expect(e.properties.$agent_is_preview).toBe(true)
        }
    })

    it('contrast: the SAME live revision with NO token is a real run — the destructive tool fires', async () => {
        const { factory, captured } = buildFactory(posthogLikeTools())
        c = await buildCluster({ mcpTransportFactory: factory })
        c.setScript([fauxCallTool('ph__delete_dashboard', { id: 7 }), fauxText('deleted')])

        await c.deployAgent({
            slug: 'real-live-mcp',
            spec: { mcps: [{ id: 'ph', url: 'https://example.com/ph' }] },
        })

        // No preview token → a real production run against live.
        const res = await request(c.ingress).post('/agents/real-live-mcp/run').send({ message: 'delete dashboard 7' })
        expect(res.status).toBe(200)

        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')
        expect(session!.is_preview).toBe(false)
        // The destructive tool actually reached the server this time.
        expect(captured.map((c) => c.name)).toContain('delete_dashboard')
        expect(captured.find((c) => c.name === 'delete_dashboard')?.args).toEqual({ id: 7 })
    })
})
