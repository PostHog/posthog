/**
 * Auth methodology for native `@posthog/*` tools and the first-party PostHog MCP.
 *
 * These tools act **as the connected PostHog user**: they target an EXPLICIT
 * `project_id` the agent passes (resolved via the `get_context` client tool or
 * `@posthog/list-projects`) and carry the caller's bearer, so the PostHog API
 * enforces the caller's access. They must NEVER inject the agent's owning team —
 * that would be ambient cross-tenant access (an agent owned by team A could read
 * team A's data for any caller who could reach it).
 *
 * Validated end to end here: an agent owned by one team, invoked by a user who
 * passes an explicit project_id, hits *that* project carrying the caller's
 * bearer — never the agent's owning team.
 */

import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js'
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import type { Transport } from '@modelcontextprotocol/sdk/shared/transport.js'
import request from 'supertest'
import { vi } from 'vitest'

import { AuthProvider, publicVerifier, readBearer } from '@posthog/agent-ingress'
import type { McpTransportFactory } from '@posthog/agent-runner'

import { buildCluster, closeSharedPool, Cluster, fauxCallTool, fauxText } from '../harness'

const AGENT_TEAM = 100
const CALLER_TEAM = 200

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
    let resolve!: (value: T) => void
    const promise = new Promise<T>((resolvePromise) => {
        resolve = resolvePromise
    })
    return { promise, resolve }
}

// A user from CALLER_TEAM authenticating with a bearer. The principal carries
// the caller's team; the bearer flows to tools as the `posthog_api` credential.
const callerProvider: AuthProvider = {
    verifiers: [
        publicVerifier,
        {
            modeType: 'posthog',
            async verify(req) {
                const bearer = readBearer(req)
                if (!bearer) {
                    return { ok: false, status: 0, reason: 'skip' }
                }
                return {
                    ok: true,
                    principal: { kind: 'posthog', user_id: 'caller', team_id: CALLER_TEAM },
                    credentials: { posthog_api: { kind: 'posthog_bearer', token: bearer } },
                }
            },
        },
    ],
}

describe('PostHog tools: act as the calling user, not the agent team', () => {
    let c: Cluster
    const fetchMock = vi.fn(
        async (_url: string | URL, _init?: RequestInit) =>
            new Response(JSON.stringify({ results: [] }), {
                status: 200,
                headers: { 'content-type': 'application/json' },
            })
    )

    beforeEach(async () => {
        fetchMock.mockClear()
        c = await buildCluster({ authProvider: callerProvider, http: { fetch: fetchMock }, teamId: AGENT_TEAM })
    })
    afterEach(async () => {
        await c.teardown()
    })
    afterAll(async () => {
        await closeSharedPool()
    })

    it('targets the explicit project_id with the caller bearer, never the agent owning team', async () => {
        c.setScript([fauxCallTool('@posthog/agent-applications-list', { project_id: CALLER_TEAM }), fauxText('listed')])
        await c.deployAgent({
            slug: 'whoami',
            teamId: AGENT_TEAM,
            spec: {
                auth: { modes: [{ type: 'posthog' }] },
                tools: [{ kind: 'native', id: '@posthog/agent-applications-list' }],
            },
        })

        const res = await request(c.ingress)
            .post('/agents/whoami/run')
            .set('authorization', 'Bearer caller-token')
            .send({ message: 'list my agents' })
        expect(res.status).toBe(200)
        await c.drain()

        const calledUrls = fetchMock.mock.calls.map((call) => String(call[0]))
        // Hits the caller's project…
        expect(calledUrls.some((u) => u.includes(`/api/projects/${CALLER_TEAM}/agent_applications/`))).toBe(true)
        // …and never the agent's owning team.
        expect(calledUrls.some((u) => u.includes(`/api/projects/${AGENT_TEAM}/`))).toBe(false)
        // …carrying the caller's bearer (acts as the user; API enforces access).
        const authHeaders = fetchMock.mock.calls.map((call) => {
            const init = call[1] as { headers?: Record<string, string> } | undefined
            return init?.headers?.Authorization
        })
        expect(authHeaders).toContain('Bearer caller-token')
    })

    it('opens the PostHog MCP with the caller bearer when a worker is already polling', async () => {
        const mcpTargets: Array<{ url: string; headers: Record<string, string> }> = []
        const mcpTransportFactory: McpTransportFactory = (target): Transport => {
            mcpTargets.push(target)
            const server = new McpServer({ name: 'posthog', version: '1.0.0' })
            server.registerTool(
                'agent-applications-list',
                { description: 'List agents', inputSchema: {} },
                async () => ({ content: [{ type: 'text' as const, text: JSON.stringify({ results: [] }) }] })
            )
            const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair()
            void server.server.connect(serverTransport)
            return clientTransport
        }

        await c.teardown()
        c = await buildCluster({
            authProvider: callerProvider,
            mcpTransportFactory,
            teamId: AGENT_TEAM,
        })
        c.setScript([fauxCallTool('posthog__agent-applications-list', { project_id: CALLER_TEAM }), fauxText('listed')])
        await c.deployAgent({
            slug: 'polling-worker',
            teamId: AGENT_TEAM,
            spec: {
                auth: { modes: [{ type: 'posthog' }] },
                tools: [
                    {
                        kind: 'client',
                        id: 'get_context',
                        description: 'Read the current PostHog Code context.',
                        args_schema: { type: 'object', properties: {}, additionalProperties: false },
                    },
                ],
                mcps: [
                    {
                        kind: 'principal',
                        id: 'posthog',
                        url: 'http://localhost:8787/mcp',
                        auth: { provider: 'posthog' },
                        default_tool_approval: 'allow',
                        tools: ['agent-applications-list'],
                    },
                ],
            },
        })

        const credentialWriteStarted = deferred<void>()
        const firstClaimFinished = deferred<boolean>()
        const credentialResolveFinished = deferred<void>()
        const originalClaim = c.queue.claim.bind(c.queue)
        const originalWrite = c.credentialBroker.write.bind(c.credentialBroker)
        const originalResolve = c.credentialBroker.resolve.bind(c.credentialBroker)

        vi.spyOn(c.queue, 'claim').mockImplementationOnce(async (timeoutMs) => {
            await credentialWriteStarted.promise
            const session = await originalClaim(timeoutMs)
            firstClaimFinished.resolve(session !== null)
            return session
        })
        vi.spyOn(c.credentialBroker, 'write').mockImplementationOnce(async (...args) => {
            credentialWriteStarted.resolve()
            if (await firstClaimFinished.promise) {
                await credentialResolveFinished.promise
            }
            await originalWrite(...args)
        })
        vi.spyOn(c.credentialBroker, 'resolve').mockImplementationOnce(async (...args) => {
            const credential = await originalResolve(...args)
            credentialResolveFinished.resolve()
            return credential
        })

        const workerLoop = c.worker.loop({ iterations: 1, claimTimeoutMs: 10 })
        const runRequest = request(c.ingress)
            .post('/agents/polling-worker/run')
            .set('authorization', 'Bearer caller-token')
            .send({ message: 'list my agents', supported_client_tools: ['get_context'] })
            .then((response) => response)
        const [res] = await Promise.all([runRequest, workerLoop])

        expect(res.status).toBe(200)
        expect(mcpTargets).toHaveLength(1)
        expect(mcpTargets[0].headers.Authorization).toBe('Bearer caller-token')
    })
})
