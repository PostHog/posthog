/**
 * Auth contract: for every route the ingress mounts, the auth it *declares*
 * (in its `TriggerModule.routes[].auth`, which `/schemas` publishes) is the
 * auth it *enforces*. This is the structural guard against the class of bug
 * that left `/listen` and `/mcp/stream` open — a route that advertises
 * `agent_spec` but forgets to authenticate would fail here.
 *
 * Data-driven from the real `TRIGGER_MODULES` registry, so a newly-added route
 * is covered automatically: forget the guard and the matching case below goes
 * red.
 */

import request from 'supertest'

import { SLACK_SIGNING_SECRET_KEY, TRIGGER_MODULES } from '@posthog/agent-ingress'

import { buildCluster, closeSharedPool, Cluster, fakeAuthProvider } from '../harness'

const PAT = 'phx_contract'

// Flatten every declared route with the trigger type that owns it.
const ALL_ROUTES = TRIGGER_MODULES.flatMap((m) => m.routes.map((r) => ({ triggerType: m.type, ...r })))

const AGENT_SPEC_ROUTES = ALL_ROUTES.filter((r) => r.auth === 'agent_spec')
const SLACK_SIGNING_ROUTES = ALL_ROUTES.filter((r) => r.auth === 'slack_signing')
const PUBLIC_ROUTES = ALL_ROUTES.filter((r) => r.auth === 'public')
const CUSTOM_ROUTES = ALL_ROUTES.filter((r) => r.auth === 'custom')

describe('auth contract: declared route auth is enforced: real e2e', () => {
    let c: Cluster

    beforeEach(async () => {
        c = await buildCluster({ authProvider: fakeAuthProvider({ posthog: PAT }) })
        // One agent with all triggers. `posthog` auth is distributed onto
        // chat/webhook/mcp; slack keeps its own signature auth, so we wire a
        // signing secret to get a clean `invalid_signature` (not a 500) when
        // an unsigned request hits the slack guard.
        await c.deployAgent({
            slug: 'contract',
            spec: { auth: { modes: [{ type: 'posthog' }] } },
            encrypted_env: { [SLACK_SIGNING_SECRET_KEY]: 'contract-signing-secret' },
        })
    })

    afterEach(async () => {
        await c.teardown()
    })

    afterAll(async () => {
        await closeSharedPool()
    })

    it('the registry actually covers the known sensitive routes', () => {
        // Cheap tripwire: if a route is dropped from the registry (and thus
        // from the cases below), this still fails loudly.
        const paths = ALL_ROUTES.map((r) => `${r.method} ${r.path}`)
        expect(paths).toContain('GET /listen')
        expect(paths).toContain('GET /mcp/stream')
        expect(paths).toContain('POST /client_tool_result')
        expect(AGENT_SPEC_ROUTES.length).toBeGreaterThanOrEqual(6)
        expect(SLACK_SIGNING_ROUTES.length).toBeGreaterThanOrEqual(2)
        expect(CUSTOM_ROUTES.length).toBeGreaterThanOrEqual(1)
        expect(PUBLIC_ROUTES.length).toBeGreaterThanOrEqual(1)
    })

    it.each(AGENT_SPEC_ROUTES)('agent_spec route $method $path → 401 without credentials', async (route) => {
        const res =
            route.method === 'GET'
                ? await request(c.ingress).get(`/agents/contract${route.path}`)
                : await request(c.ingress).post(`/agents/contract${route.path}`).send({})
        expect(res.status).toBe(401)
    })

    it.each(SLACK_SIGNING_ROUTES)(
        'slack_signing route $method $path → 401 invalid_signature without a signature',
        async (route) => {
            const res = await request(c.ingress).post(`/agents/contract${route.path}`).send({})
            expect(res.status).toBe(401)
            expect(res.body.error).toBe('invalid_signature')
        }
    )

    it.each(PUBLIC_ROUTES)('public route $method $path is reachable without credentials', async (route) => {
        const res =
            route.method === 'GET'
                ? await request(c.ingress).get(`/agents/contract${route.path}`)
                : await request(c.ingress).post(`/agents/contract${route.path}`).send({})
        // "Reachable" = the auth layer didn't reject it. The handler may still
        // 200 or 4xx on its own logic, but never an auth rejection.
        expect(res.status).not.toBe(401)
        expect(res.status).not.toBe(403)
    })

    // `custom` routes (MCP `/mcp`) authorize per JSON-RPC method: `initialize`
    // is allowed pre-auth, everything else must authenticate.
    it('custom route POST /mcp: a non-initialize call without creds → RPC unauthorized (-32001)', async () => {
        const res = await request(c.ingress)
            .post('/agents/contract/mcp')
            .send({ jsonrpc: '2.0', id: 1, method: 'tools/list' })
        expect(res.body.error?.code).toBe(-32001)
    })

    it('custom route POST /mcp: initialize is allowed pre-auth (the only bypass)', async () => {
        const res = await request(c.ingress)
            .post('/agents/contract/mcp')
            .send({ jsonrpc: '2.0', id: 1, method: 'initialize' })
        expect(res.body.result?.serverInfo?.name).toBe('agent:contract')
    })
})
