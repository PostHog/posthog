/**
 * Auth methodology for the native `@posthog/*` data tools.
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

import request from 'supertest'
import { vi } from 'vitest'

import { AuthProvider, publicVerifier, readBearer } from '@posthog/agent-ingress'

import { buildCluster, closeSharedPool, Cluster, fauxCallTool, fauxText } from '../harness'

const AGENT_TEAM = 100
const CALLER_TEAM = 200

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

describe('@posthog/* data tools: act as the calling user, not the agent team', () => {
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
})
