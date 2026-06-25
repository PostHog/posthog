import { createHmac, randomUUID } from 'crypto'
import { Pool } from 'pg'
import request from 'supertest'

import {
    AgentSpecSchema,
    PgApprovalStore,
    PgCredentialBroker,
    PgRevisionStore,
    PgSessionQueue,
    RedisSessionEventBus,
} from '@posthog/agent-shared'
import type { AgentApplication, AgentRevision } from '@posthog/agent-shared'
import { reset } from '@posthog/agent-shared/testing'

import type { AuthProvider } from '../enqueue/auth'
import { buildDefaultVerifiers, type PosthogIdentityIntrospector, type TeamOrgLookup } from '../enqueue/verifiers'
import { buildApp } from './server'

// Fake PostHog identity introspection for the principal-authed read routes.
// `owner-token` is a real user on the agent's team (1) / org (org-A);
// `org-peer-token` is a different user in the same org (admitted by an
// `organization`-audience agent, but NOT the session owner). No token → the
// public path yields an anonymous principal.
const OWNER_TOKEN = 'owner-token'
const ORG_PEER_TOKEN = 'org-peer-token'
const testIntrospector: PosthogIdentityIntrospector = {
    async introspect(bearer) {
        if (bearer === OWNER_TOKEN) {
            return { uuid: 'owner', email: 'owner@test', team: { id: 1 }, organization: { id: 'org-A' } }
        }
        if (bearer === ORG_PEER_TOKEN) {
            return { uuid: 'peer', email: 'peer@test', organizations: [{ id: 'org-A' }] }
        }
        return null
    },
    async canAccessTeam(bearer, teamId) {
        return bearer === OWNER_TOKEN && teamId === 1
    },
}
const testTeamOrg: TeamOrgLookup = {
    async orgForTeam(teamId) {
        return teamId === 1 ? 'org-A' : null
    },
}
const noSecret = { resolve: async (): Promise<string | null> => null }
const testAuthProvider: AuthProvider = {
    verifiers: buildDefaultVerifiers({
        introspector: testIntrospector,
        teamOrg: testTeamOrg,
        jwtSecretResolver: noSecret,
        sharedSecretResolver: noSecret,
        internalSecret: 'test-internal',
    }),
}

const TEST_SLACK_SECRET = 'test-slack-secret'

const TEST_DB_URL =
    process.env.AGENT_TEST_DB_URL ?? 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue_test'
// nosemgrep: trailofbits.generic.redis-unencrypted-transport.redis-unencrypted-transport
const REDIS_URL = process.env.REDIS_URL ?? 'redis://localhost:6379'
const HARNESS_ENCRYPTION_SALT_KEYS = '01234567890123456789012345678901'

/**
 * Mints the `(timestamp, signature)` pair Slack would send for a given body.
 * Slack signs `v0:<ts>:<rawBody>` with the shared signing secret; the ingress
 * verifies the exact same HMAC. Used by every `/slack/*` test case below
 * since every Slack route requires a verified signature now.
 */
function signSlack(body: string, secret = TEST_SLACK_SECRET): { ts: string; sig: string } {
    const ts = String(Math.floor(Date.now() / 1000))
    const mac = createHmac('sha256', secret).update(`v0:${ts}:${body}`).digest('hex')
    return { ts, sig: `v0=${mac}` }
}

async function seedApp(store: PgRevisionStore, slug: string): Promise<{ app: AgentApplication; rev: AgentRevision }> {
    const app = await store.createApplication({ team_id: 1, slug, name: slug, description: '' })
    const rev = await store.createRevision({
        application_id: app.id,
        parent_revision_id: null,
        created_by_id: null,
        bundle_uri: 's3://x/',
        spec: AgentSpecSchema.parse({
            model: 'test/x',
            // These tests exercise the routing surface, not auth — keep the
            // "open agent" behaviour so request flows succeed without a verifier.
            // Public exposure is opt-in (see AuthModeSchema) so each declarative
            // trigger sets it explicitly; slack is intrinsic (no modes).
            triggers: [
                { type: 'chat', config: {}, auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] } },
                { type: 'slack', config: { trusted_workspaces: '*' } },
                {
                    type: 'webhook',
                    config: { path: '/webhook' },
                    auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] },
                },
                { type: 'mcp', config: {}, auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] } },
            ],
        }),
    })
    await store.setRevisionState(rev.id, 'live')
    await store.setLiveRevision(app.id, rev.id)
    return { app, rev }
}

/**
 * Like {@link seedApp} but the chat trigger requires a PostHog
 * `organization`-audience principal — the agent-builder's auth shape, where any
 * org member may invoke (cross-project) but session ownership is still
 * per-user. Pair with `mk({}, { withAuth: true })`.
 */
async function seedPosthogApp(
    store: PgRevisionStore,
    slug: string
): Promise<{ app: AgentApplication; rev: AgentRevision }> {
    const app = await store.createApplication({ team_id: 1, slug, name: slug, description: '' })
    const rev = await store.createRevision({
        application_id: app.id,
        parent_revision_id: null,
        created_by_id: null,
        bundle_uri: 's3://x/',
        spec: AgentSpecSchema.parse({
            model: 'test/x',
            triggers: [
                {
                    type: 'chat',
                    config: {},
                    auth: { modes: [{ type: 'posthog', scopes: [], audience: 'organization' }] },
                },
            ],
        }),
    })
    await store.setRevisionState(rev.id, 'live')
    await store.setLiveRevision(app.id, rev.id)
    return { app, rev }
}

describe('ingress HTTP server (path mode)', () => {
    let pool: Pool
    let bus: RedisSessionEventBus

    beforeAll(async () => {
        pool = new Pool({ connectionString: TEST_DB_URL })
        bus = new RedisSessionEventBus({
            url: REDIS_URL,
            channelPrefix: `ingress_server_test_${Math.random().toString(36).slice(2, 10)}`,
        })
        await bus.connect()
    })

    beforeEach(async () => {
        await reset({ databaseUrl: TEST_DB_URL })
    })

    afterAll(async () => {
        await bus.disconnect()
        await pool.end()
    })

    function mk(
        routing?: { routingMode: 'domain' | 'path'; domainSuffix?: string },
        opts?: { withAuth?: boolean }
    ): {
        revisions: PgRevisionStore
        queue: PgSessionQueue
        approvals: PgApprovalStore
        bus: RedisSessionEventBus
        app: ReturnType<typeof buildApp>
    } {
        const revisions = new PgRevisionStore(pool)
        const queue = new PgSessionQueue(pool)
        const approvals = new PgApprovalStore(pool)
        const credentialBroker = new PgCredentialBroker(pool, {
            encryptionSaltKeys: HARNESS_ENCRYPTION_SALT_KEYS,
        })
        const app = buildApp({
            revisions,
            queue,
            approvals,
            bus,
            credentialBroker,
            // Opt in to the PostHog identity verifiers for the principal-authed
            // read-route tests; default stays public-only like the rest.
            ...(opts?.withAuth ? { authProvider: testAuthProvider } : {}),
            routingMode: routing?.routingMode ?? 'path',
            domainSuffix: routing?.domainSuffix,
            pathPrefix: '/agents',
            // Returns the test secret for every `(secretRef, application)`
            // lookup. Models the "PostHog runs one Slack app for everything"
            // deployment without needing each fixture to populate an
            // `encrypted_env`.
            slackSigningSecretResolver: {
                async resolve(): Promise<string | null> {
                    return TEST_SLACK_SECRET
                },
            },
        })
        return { revisions, queue, approvals, bus, app }
    }

    it('GET /healthz returns ok', async () => {
        const { app } = mk()
        const res = await request(app).get('/healthz')
        expect(res.status).toBe(200)
        expect(res.body).toEqual({ ok: true })
    })

    it('404s an unknown agent slug', async () => {
        const { app } = mk()
        const res = await request(app).post('/agents/ghost/webhook').send({ data: 'x' })
        expect(res.status).toBe(404)
    })

    it('POST /run creates a chat session', async () => {
        const { revisions, queue, app } = mk()
        await seedApp(revisions, 'weekly-digest')
        const res = await request(app).post('/agents/weekly-digest/run').send({ message: 'hi', external_key: 'ext-1' })
        expect(res.status).toBe(200)
        expect(res.body.session_id).not.toBeUndefined()
        const session = await queue.get(res.body.session_id)
        expect(session!.conversation[0]).toMatchObject({ role: 'user', content: 'hi' })
    })

    it('POST /send buffers into pending_inputs (drained by runner at next turn)', async () => {
        const { revisions, queue, app } = mk()
        await seedApp(revisions, 'x')
        const createRes = await request(app).post('/agents/x/run').send({ message: 'first' })
        const sid = createRes.body.session_id
        const sendRes = await request(app).post('/agents/x/send').send({ session_id: sid, message: 'second' })
        expect(sendRes.status).toBe(200)
        const session = await queue.get(sid)
        expect(session!.conversation).toHaveLength(1)
        expect(session!.pending_inputs).toHaveLength(1)
    })

    it('POST /slack/events handles url_verification challenge', async () => {
        const { revisions, app } = mk()
        // Slack signs url_verification with the same signing secret the agent
        // configures, so the agent has to exist + the resolver has to return
        // the secret before the challenge round-trip works.
        await seedApp(revisions, 'foo')
        const body = JSON.stringify({ type: 'url_verification', challenge: 'xyz' })
        const { ts, sig } = signSlack(body)
        const res = await request(app)
            .post('/agents/foo/slack/events')
            .set('content-type', 'application/json')
            .set('x-slack-request-timestamp', ts)
            .set('x-slack-signature', sig)
            .send(body)
        expect(res.status).toBe(200)
        expect(res.body.challenge).toBe('xyz')
    })

    it('POST /slack/events with thread_ts uses externalKey for resume', async () => {
        const { revisions, queue, app } = mk()
        await seedApp(revisions, 'echo')
        const firstBody = JSON.stringify({
            type: 'event_callback',
            event: { type: 'message', channel: 'C01', user: 'U01', text: 'hi', ts: '1.0', thread_ts: '1.0' },
        })
        const firstSig = signSlack(firstBody)
        const first = await request(app)
            .post('/agents/echo/slack/events')
            .set('content-type', 'application/json')
            .set('x-slack-request-timestamp', firstSig.ts)
            .set('x-slack-signature', firstSig.sig)
            .send(firstBody)
        const secondBody = JSON.stringify({
            type: 'event_callback',
            event: { type: 'message', channel: 'C01', user: 'U01', text: 'follow', ts: '1.1', thread_ts: '1.0' },
        })
        const secondSig = signSlack(secondBody)
        const second = await request(app)
            .post('/agents/echo/slack/events')
            .set('content-type', 'application/json')
            .set('x-slack-request-timestamp', secondSig.ts)
            .set('x-slack-signature', secondSig.sig)
            .send(secondBody)
        expect(first.body.resumed).toBe(false)
        expect(second.body.resumed).toBe(true)
        expect(second.body.session_id).toBe(first.body.session_id)
        const session = await queue.get(first.body.session_id)
        // First message lands in conversation (fresh session). Second goes
        // into pending_inputs (resume of a still-live session).
        expect(session!.conversation).toHaveLength(1)
        expect(session!.pending_inputs).toHaveLength(1)
    })

    it('POST /webhook creates a session with body as content', async () => {
        const { revisions, queue, app } = mk()
        await seedApp(revisions, 'wh')
        const res = await request(app)
            .post('/agents/wh/webhook')
            .send({ payload: { x: 1 } })
        const session = await queue.get(res.body.session_id)
        expect(session!.conversation[0].content).toBe(JSON.stringify({ payload: { x: 1 } }))
    })

    it('POST /mcp initialize returns server info with slug', async () => {
        const { revisions, app } = mk()
        await seedApp(revisions, 'weekly-digest')
        const res = await request(app)
            .post('/agents/weekly-digest/mcp')
            .send({ jsonrpc: '2.0', id: 1, method: 'initialize' })
        expect(res.body.result.serverInfo.name).toBe('agent:weekly-digest')
    })

    it('POST /mcp tools/list returns the ask tool', async () => {
        const { revisions, app } = mk()
        await seedApp(revisions, 'x')
        const res = await request(app).post('/agents/x/mcp').send({ jsonrpc: '2.0', id: 1, method: 'tools/list' })
        expect(res.body.result.tools[0].name).toBe('ask')
        // Inputs include the optional session_id for continuation.
        expect(res.body.result.tools[0].inputSchema.properties.session_id).not.toBeUndefined()
    })

    it('POST /mcp tools/call name=ask enqueues a session', async () => {
        const { revisions, queue, app } = mk()
        await seedApp(revisions, 'x')
        const res = await request(app)
            .post('/agents/x/mcp')
            .send({
                jsonrpc: '2.0',
                id: 1,
                method: 'tools/call',
                params: { name: 'ask', arguments: { message: 'hi via mcp' } },
            })
        const parsed = JSON.parse(res.body.result.content[0].text)
        expect(parsed.session_id).not.toBeUndefined()
        expect(parsed.state).toBe('queued')
        const session = await queue.get(parsed.session_id)
        expect(session!.conversation[0].content).toBe('hi via mcp')
    })

    // Trigger-edge validation: the chat trigger used to silently coerce a
    // missing / wrong-shaped `message` into the empty string, then enqueue a
    // session that died at the model layer. zod parsing at the edge turns
    // each of those into a clean 400 with the issue list.
    it('POST /run with empty message returns 400 with zod issues', async () => {
        const { revisions, app } = mk()
        await seedApp(revisions, 'x')
        const res = await request(app).post('/agents/x/run').send({ message: '' })
        expect(res.status).toBe(400)
        expect(res.body.error).toBe('invalid_body')
        expect(res.body.issues[0].path).toEqual(['message'])
    })

    it('POST /run wrapped in {input: ...} returns 400 (the exact mistake from authoring)', async () => {
        const { revisions, app } = mk()
        await seedApp(revisions, 'x')
        const res = await request(app)
            .post('/agents/x/run')
            .send({ input: { message: 'hi' } })
        expect(res.status).toBe(400)
        expect(res.body.error).toBe('invalid_body')
        expect(res.body.issues[0].path).toEqual(['message'])
    })

    it('POST /send with non-UUID session_id returns 400', async () => {
        const { revisions, app } = mk()
        await seedApp(revisions, 'x')
        const res = await request(app).post('/agents/x/send').send({ session_id: 'nope', message: 'hi' })
        expect(res.status).toBe(400)
        expect(res.body.error).toBe('invalid_body')
        expect(res.body.issues[0].path).toEqual(['session_id'])
    })

    // Schema-publish: every trigger the agent has should appear, with the
    // auth requirement resolved against the agent's `spec.auth` — callers
    // learn the full API surface (and how to authenticate to each route)
    // from one GET. No grepping the trigger source.
    it('GET /schemas cascades from spec.triggers across every trigger module', async () => {
        const { revisions, app } = mk()
        await seedApp(revisions, 'discoverable')
        const res = await request(app).get('/agents/discoverable/schemas')
        expect(res.status).toBe(200)
        expect(res.body.agent).toEqual({ slug: 'discoverable', name: 'discoverable' })
        const byType = Object.fromEntries(
            (res.body.triggers as Array<{ type: string; routes: unknown[] }>).map((t) => [t.type, t])
        )
        // seedApp wires all four triggers; the registry should publish all of them.
        expect(Object.keys(byType).sort()).toEqual(['chat', 'mcp', 'slack', 'webhook'])
    })

    it('GET /schemas publishes the chat trigger body shape + per-route auth', async () => {
        const { revisions, app } = mk()
        await seedApp(revisions, 'discoverable')
        const res = await request(app).get('/agents/discoverable/schemas')
        const chat = (res.body.triggers as Array<{ type: string; routes: unknown[] }>).find((t) => t.type === 'chat')!
        const routesByPath = Object.fromEntries(
            (
                chat.routes as Array<{
                    method: string
                    path: string
                    bodySchema?: { properties?: Record<string, unknown>; required?: string[] }
                    querySchema?: unknown
                    auth: { modes?: Array<{ type: string }>; mode?: string }
                }>
            ).map((r) => [`${r.method} ${r.path}`, r])
        )
        expect(routesByPath['POST /run'].bodySchema!.properties!.message).toMatchObject({
            type: 'string',
            minLength: 1,
        })
        expect(routesByPath['POST /run'].bodySchema!.required).toContain('message')
        // seedApp deliberately opts into public exposure (these tests
        // exercise the routing surface, not auth) → every chat route
        // advertises the modes verbatim.
        expect(routesByPath['POST /run'].auth).toEqual({
            modes: [{ type: 'public', acknowledge_public_exposure: true }],
        })
        expect(routesByPath['GET /listen'].querySchema).not.toBeUndefined()
    })

    it('GET /schemas advertises slack signing auth on the slack route', async () => {
        const { revisions, app } = mk()
        await seedApp(revisions, 'discoverable')
        const res = await request(app).get('/agents/discoverable/schemas')
        const slack = (res.body.triggers as Array<{ type: string; routes: unknown[] }>).find((t) => t.type === 'slack')!
        const route = (slack.routes as Array<{ path: string; auth: { mode: string; header?: string } }>)[0]
        expect(route.path).toBe('/slack/events')
        expect(route.auth).toEqual({ mode: 'slack_signing', header: 'X-Slack-Signature' })
    })

    // Edge validation on the non-chat triggers — same pattern as chat, just
    // for the cases that actually have a contract worth enforcing.

    it('POST /webhook with a non-object body returns 400 (instead of seeding "[]")', async () => {
        const { revisions, app } = mk()
        await seedApp(revisions, 'wh')
        const res = await request(app).post('/agents/wh/webhook').send([])
        expect(res.status).toBe(400)
        expect(res.body.error).toBe('invalid_body')
    })

    it('POST /mcp initialize mints an Mcp-Session-Id when the client did not send one', async () => {
        const { revisions, app } = mk()
        await seedApp(revisions, 'x')
        const res = await request(app).post('/agents/x/mcp').send({ jsonrpc: '2.0', id: 1, method: 'initialize' })
        // Standard streamable-HTTP session header — real MCP clients pick
        // this up and echo it on every subsequent request.
        const minted = res.headers['mcp-session-id'] as string | undefined
        expect(minted).toMatch(/^[0-9a-f-]{36}$/)
    })

    it('POST /mcp initialize does NOT re-mint when the client already sent an Mcp-Session-Id', async () => {
        const { revisions, app } = mk()
        await seedApp(revisions, 'x')
        const res = await request(app)
            .post('/agents/x/mcp')
            .set('Mcp-Session-Id', 'client-supplied')
            .send({ jsonrpc: '2.0', id: 1, method: 'initialize' })
        // Server only mints when missing — client's id wins.
        expect(res.headers['mcp-session-id']).toBeUndefined()
    })

    it('POST /mcp tools/call ask with session_id continues an existing session', async () => {
        const { revisions, queue, app } = mk()
        await seedApp(revisions, 'x')
        const initial = await request(app)
            .post('/agents/x/mcp')
            .send({
                jsonrpc: '2.0',
                id: 1,
                method: 'tools/call',
                params: { name: 'ask', arguments: { message: 'first' } },
            })
        const sid = JSON.parse(initial.body.result.content[0].text).session_id as string
        // Mark the queue session running so it isn't terminal — continuation
        // appends into pending_inputs.
        await queue.update(sid, { state: 'running' })
        const followup = await request(app)
            .post('/agents/x/mcp')
            .send({
                jsonrpc: '2.0',
                id: 2,
                method: 'tools/call',
                params: { name: 'ask', arguments: { message: 'second', session_id: sid } },
            })
        expect(JSON.parse(followup.body.result.content[0].text).session_id).toBe(sid)
        const after = await queue.get(sid)
        // Original conversation seed + the queued follow-up.
        expect(after!.conversation).toHaveLength(1)
        expect(after!.pending_inputs).toHaveLength(1)
        expect(after!.pending_inputs[0].content).toBe('second')
    })

    it('POST /mcp tools/call ask returns invalid_params for a missing message', async () => {
        const { revisions, app } = mk()
        await seedApp(revisions, 'x')
        const res = await request(app)
            .post('/agents/x/mcp')
            .send({
                jsonrpc: '2.0',
                id: 1,
                method: 'tools/call',
                params: { name: 'ask', arguments: {} },
            })
        expect(res.body.error.code).toBe(-32602)
    })

    it('POST /mcp tools/call rejects unknown tool name', async () => {
        const { revisions, app } = mk()
        await seedApp(revisions, 'x')
        const res = await request(app)
            .post('/agents/x/mcp')
            .send({
                jsonrpc: '2.0',
                id: 1,
                method: 'tools/call',
                params: { name: 'shout', arguments: { message: 'hi' } },
            })
        expect(res.body.error.code).toBe(-32601)
    })

    it('POST /mcp resources/list scopes by Mcp-Session-Id header on a public agent', async () => {
        const { revisions, app } = mk()
        await seedApp(revisions, 'x')
        // Client A creates a session, tagged with its Mcp-Session-Id header.
        const aCreate = await request(app)
            .post('/agents/x/mcp')
            .set('Mcp-Session-Id', 'client-A')
            .send({
                jsonrpc: '2.0',
                id: 1,
                method: 'tools/call',
                params: { name: 'ask', arguments: { message: 'from A' } },
            })
        const aSessionId = JSON.parse(aCreate.body.result.content[0].text).session_id as string
        // Client B does the same with its own header.
        const bCreate = await request(app)
            .post('/agents/x/mcp')
            .set('Mcp-Session-Id', 'client-B')
            .send({
                jsonrpc: '2.0',
                id: 1,
                method: 'tools/call',
                params: { name: 'ask', arguments: { message: 'from B' } },
            })
        const bSessionId = JSON.parse(bCreate.body.result.content[0].text).session_id as string
        // resources/list as A: only A's session shows up.
        const listA = await request(app)
            .post('/agents/x/mcp')
            .set('Mcp-Session-Id', 'client-A')
            .send({ jsonrpc: '2.0', id: 1, method: 'resources/list' })
        const aUris = (listA.body.result.resources as Array<{ uri: string }>).map((r) => r.uri)
        expect(aUris).toContain(`agent://session/${aSessionId}`)
        expect(aUris).not.toContain(`agent://session/${bSessionId}`)
        // A client with no Mcp-Session-Id sees nothing in list (security
        // default — prevents enumeration of other clients' sessions on a
        // public agent). It can still read by URI if it has the id.
        const listAnon = await request(app)
            .post('/agents/x/mcp')
            .send({ jsonrpc: '2.0', id: 1, method: 'resources/list' })
        expect(listAnon.body.result.resources).toEqual([])
    })

    it('POST /mcp resources/read on a public agent allows reads by URI possession', async () => {
        // Capability model — possession of the agent://session/<uuid> URI
        // is the secret. A different anonymous client (no header, no
        // principal) can read the session if it has the id. The 122 bits
        // of UUID entropy prevent guessing.
        const { revisions, app } = mk()
        await seedApp(revisions, 'x')
        const create = await request(app)
            .post('/agents/x/mcp')
            .set('Mcp-Session-Id', 'creator')
            .send({
                jsonrpc: '2.0',
                id: 1,
                method: 'tools/call',
                params: { name: 'ask', arguments: { message: 'mine' } },
            })
        const sessionId = JSON.parse(create.body.result.content[0].text).session_id as string
        // Same client reads — works.
        const owner = await request(app)
            .post('/agents/x/mcp')
            .set('Mcp-Session-Id', 'creator')
            .send({
                jsonrpc: '2.0',
                id: 1,
                method: 'resources/read',
                params: { uri: `agent://session/${sessionId}` },
            })
        expect(owner.body.result.contents[0].text).toContain(sessionId)
    })

    it('POST /mcp respects spec.auth — a pat-gated agent rejects unauthenticated calls', async () => {
        const { revisions, app } = mk()
        // Seed an agent with PAT auth (default app is public).
        const store = revisions
        const agentApp = await store.createApplication({
            team_id: 1,
            slug: 'gated',
            name: 'gated',
            description: '',
        })
        const rev = await store.createRevision({
            application_id: agentApp.id,
            parent_revision_id: null,
            created_by_id: null,
            bundle_uri: 's3://x/',
            spec: AgentSpecSchema.parse({
                model: 'test/x',
                triggers: [{ type: 'mcp', config: {}, auth: { modes: [{ type: 'posthog' }] } }],
            }),
        })
        await store.setRevisionState(rev.id, 'live')
        await store.setLiveRevision(agentApp.id, rev.id)
        // tools/list without a bearer token → RPC_UNAUTHORIZED (-32001).
        // The default app-build wires PUBLIC_ONLY_AUTH_PROVIDER, which
        // rejects every PAT, so any call to a PAT-mode agent fails here.
        const res = await request(app).post('/agents/gated/mcp').send({ jsonrpc: '2.0', id: 1, method: 'tools/list' })
        expect(res.body.error.code).toBe(-32001)
        // initialize is allowed pre-auth so a client can discover capabilities
        // before being asked to authenticate.
        const init = await request(app).post('/agents/gated/mcp').send({ jsonrpc: '2.0', id: 1, method: 'initialize' })
        expect(init.body.result.serverInfo.name).toBe('agent:gated')
    })

    it('cross-agent session access is 404 — a session id from agent A cannot be driven via agent B', async () => {
        const { revisions, app } = mk()
        // Two public agents in the same team → distinct application_ids. Both
        // store the anonymous principal, so `principalsMatch` alone would let a
        // leaked session id be driven through either agent's endpoints. The
        // `application_id` binding closes that cross-tenant path.
        await seedApp(revisions, 'agent-a')
        await seedApp(revisions, 'agent-b')
        const create = await request(app).post('/agents/agent-a/run').send({ message: 'hi' })
        expect(create.status).toBe(200)
        const sid = create.body.session_id as string

        // Every write/stream path on agent B must refuse A's session as not-found.
        const crossAgentCases: Array<() => Promise<{ status: number }>> = [
            () => request(app).post('/agents/agent-b/send').send({ session_id: sid, message: 'pwn' }),
            () => request(app).post('/agents/agent-b/cancel').send({ session_id: sid }),
            () => request(app).get('/agents/agent-b/listen').query({ session_id: sid }),
            () =>
                request(app)
                    .post('/agents/agent-b/client_tool_result')
                    .send({ session_id: sid, call_id: 'c1', result: {} }),
            () => request(app).get('/agents/agent-b/mcp/stream').query({ session_id: sid }),
        ]
        for (const makeRequest of crossAgentCases) {
            expect((await makeRequest()).status).toBe(404)
        }

        // The owning agent still drives its own session.
        const sendA = await request(app).post('/agents/agent-a/send').send({ session_id: sid, message: 'ok' })
        expect(sendA.status).toBe(200)
    })

    it('GET /mcp/connect-info advertises a public agent with no headers', async () => {
        const { revisions, app } = mk()
        await seedApp(revisions, 'public-agent')
        const res = await request(app).get('/agents/public-agent/mcp/connect-info')
        expect(res.status).toBe(200)
        expect(res.body.url).toMatch(/\/agents\/public-agent\/mcp$/)
        expect(res.body.transport).toBe('http')
        expect(res.body.auth.mode).toBe('public')
        expect(res.body.auth.header).toBeNull()
        // No --header flags when no auth is required.
        expect(res.body.snippets.claude_code_command).not.toContain('--header')
        expect(res.body.snippets.mcp_json.mcpServers['public-agent'].headers).toBeUndefined()
    })

    it('GET /mcp/connect-info uses the domain-mode URL (slug in host, no /agents prefix)', async () => {
        // Domain mode: the agent is reachable at <slug><suffix>, routes at root.
        // The connect URL must mirror that, not the path-mode /agents/<slug>/mcp.
        const { revisions, app } = mk({ routingMode: 'domain', domainSuffix: '.agents.test' })
        await seedApp(revisions, 'dom-agent')
        const res = await request(app).get('/mcp/connect-info').set('Host', 'dom-agent.agents.test')
        expect(res.status).toBe(200)
        expect(res.body.url).toBe('https://dom-agent.agents.test/mcp')
        expect(res.body.snippets.mcp_json.mcpServers['dom-agent'].url).toBe('https://dom-agent.agents.test/mcp')
    })

    it('GET /mcp/connect-info renders Bearer placeholder for a PAT-gated agent', async () => {
        const { revisions, app } = mk()
        const store = revisions
        const agentApp = await store.createApplication({
            team_id: 1,
            slug: 'pat-gated',
            name: 'pat-gated',
            description: '',
        })
        const rev = await store.createRevision({
            application_id: agentApp.id,
            parent_revision_id: null,
            created_by_id: null,
            bundle_uri: 's3://x/',
            spec: AgentSpecSchema.parse({
                model: 'test/x',
                triggers: [{ type: 'mcp', config: {}, auth: { modes: [{ type: 'posthog' }] } }],
            }),
        })
        await store.setRevisionState(rev.id, 'live')
        await store.setLiveRevision(agentApp.id, rev.id)
        const res = await request(app).get('/agents/pat-gated/mcp/connect-info')
        expect(res.body.auth.mode).toBe('posthog')
        expect(res.body.auth.header).toBe('Authorization')
        // Placeholder only — never a real secret.
        expect(res.body.snippets.mcp_json.mcpServers['pat-gated'].headers.Authorization).toBe(
            'Bearer <YOUR_POSTHOG_API_KEY>'
        )
        expect(res.body.snippets.claude_code_command).toContain('Authorization=Bearer <YOUR_POSTHOG_API_KEY>')
    })

    it('GET /mcp/connect-info 404s when the agent has no mcp trigger', async () => {
        const { revisions, app } = mk()
        const store = revisions
        const agentApp = await store.createApplication({
            team_id: 1,
            slug: 'no-mcp',
            name: 'no-mcp',
            description: '',
        })
        const rev = await store.createRevision({
            application_id: agentApp.id,
            parent_revision_id: null,
            created_by_id: null,
            bundle_uri: 's3://x/',
            spec: AgentSpecSchema.parse({
                model: 'test/x',
                triggers: [
                    {
                        type: 'chat',
                        config: {},
                        auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] },
                    },
                ],
            }),
        })
        await store.setRevisionState(rev.id, 'live')
        await store.setLiveRevision(agentApp.id, rev.id)
        const res = await request(app).get('/agents/no-mcp/mcp/connect-info')
        expect(res.status).toBe(404)
        expect(res.body.error).toBe('no_mcp_trigger')
    })

    it('POST /mcp with the wrong jsonrpc version returns 400', async () => {
        const { revisions, app } = mk()
        await seedApp(revisions, 'm')
        const res = await request(app).post('/agents/m/mcp').send({ jsonrpc: '1.0', id: 1, method: 'initialize' })
        expect(res.status).toBe(400)
        expect(res.body.error).toBe('invalid_body')
        expect(res.body.issues[0].path).toEqual(['jsonrpc'])
    })

    it('GET /mcp/stream without a session_id returns 400', async () => {
        const { revisions, app } = mk()
        await seedApp(revisions, 'm')
        const res = await request(app).get('/agents/m/mcp/stream')
        expect(res.status).toBe(400)
        expect(res.body.error).toBe('invalid_body')
    })

    it('GET /schemas 404s for an unknown agent', async () => {
        const { app } = mk()
        const res = await request(app).get('/agents/ghost/schemas')
        expect(res.status).toBe(404)
        expect(res.body.error).toBe('no_agent')
    })

    // Regression: malformed JSON used to produce express's default HTML
    // SyntaxError page. The global errorHandler now translates it to a
    // structured 400.
    it('POST /run with malformed JSON returns 400 invalid_json', async () => {
        const { revisions, app } = mk()
        await seedApp(revisions, 'x')
        const res = await request(app).post('/agents/x/run').set('Content-Type', 'application/json').send('{not json')
        expect(res.status).toBe(400)
        expect(res.body.error).toBe('invalid_json')
    })

    // Principal-authed read routes — the inline approval card + transcript reload
    // fetch straight from the ingress (cross-project), gated by principal-match.
    // The owner reads their own session; a same-org peer can't; and a public
    // (anonymous) caller is refused outright — `principalsMatch` treats all
    // anonymous principals as equal, so it can't gate a public agent.

    async function queueApproval(
        approvals: PgApprovalStore,
        opts: { sessionId: string; appId: string; revId: string; type: 'principal' | 'agent' }
    ): Promise<string> {
        const id = randomUUID()
        await approvals.upsertQueued({
            id,
            session_id: opts.sessionId,
            application_id: opts.appId,
            team_id: 1,
            revision_id: opts.revId,
            turn: 0,
            tool_call_id: 'tc-1',
            tool_name: 'danger',
            proposed_args: { x: 1 },
            assistant_message: { role: 'assistant', content: [{ type: 'text', text: '' }], timestamp: Date.now() },
            approver_scope: { type: opts.type, allow_edit: false },
            expires_at: new Date(Date.now() + 60_000).toISOString(),
        })
        return id
    }

    it('GET /sessions/:id returns the transcript for the session principal', async () => {
        const { revisions, app } = mk(undefined, { withAuth: true })
        await seedPosthogApp(revisions, 'sess')
        const run = await request(app)
            .post('/agents/sess/run')
            .set('Authorization', `Bearer ${OWNER_TOKEN}`)
            .send({ message: 'hello' })
        const res = await request(app)
            .get(`/agents/sess/sessions/${run.body.session_id}`)
            .set('Authorization', `Bearer ${OWNER_TOKEN}`)
        expect(res.status).toBe(200)
        expect(res.body.id).toBe(run.body.session_id)
        expect(res.body.conversation).toHaveLength(1)
        expect(res.body.conversation_trimmed).toBe(false)
    })

    // The security property the whole feature rests on: a public-auth agent
    // hands every caller the same anonymous principal, so the read routes MUST
    // refuse it — otherwise any anonymous caller could read any session by id.
    it('GET /sessions/:id refuses an anonymous (public-auth) caller', async () => {
        const { revisions, app } = mk()
        await seedApp(revisions, 'pubsess')
        const run = await request(app).post('/agents/pubsess/run').send({ message: 'secret' })
        const res = await request(app).get(`/agents/pubsess/sessions/${run.body.session_id}`)
        expect(res.status).toBe(403)
        expect(res.body.error).toBe('forbidden')
    })

    it('GET /sessions/:id refuses a same-org peer who is not the session owner', async () => {
        const { revisions, app } = mk(undefined, { withAuth: true })
        await seedPosthogApp(revisions, 'sesspeer')
        const run = await request(app)
            .post('/agents/sesspeer/run')
            .set('Authorization', `Bearer ${OWNER_TOKEN}`)
            .send({ message: 'hello' })
        const res = await request(app)
            .get(`/agents/sesspeer/sessions/${run.body.session_id}`)
            .set('Authorization', `Bearer ${ORG_PEER_TOKEN}`)
        expect(res.status).toBe(403)
        expect(res.body.error).toBe('not_session_principal')
    })

    it('GET /sessions/:id 404s an unknown session', async () => {
        const { revisions, app } = mk(undefined, { withAuth: true })
        await seedPosthogApp(revisions, 'sess404')
        const res = await request(app)
            .get(`/agents/sess404/sessions/${randomUUID()}`)
            .set('Authorization', `Bearer ${OWNER_TOKEN}`)
        expect(res.status).toBe(404)
    })

    // Regression: `slice(-0)` is `slice(0)` (the whole array), so `last_n=0` must
    // fall through to the untrimmed branch — not return zero messages.
    it('GET /sessions/:id?last_n=0 returns the full transcript, untrimmed', async () => {
        const { revisions, app } = mk(undefined, { withAuth: true })
        await seedPosthogApp(revisions, 'sess0')
        const run = await request(app)
            .post('/agents/sess0/run')
            .set('Authorization', `Bearer ${OWNER_TOKEN}`)
            .send({ message: 'hello' })
        const res = await request(app)
            .get(`/agents/sess0/sessions/${run.body.session_id}?last_n=0`)
            .set('Authorization', `Bearer ${OWNER_TOKEN}`)
        expect(res.status).toBe(200)
        expect(res.body.conversation).toHaveLength(1)
        expect(res.body.conversation_trimmed).toBe(false)
    })

    it('GET /sessions/:id?last_n trims to the trailing messages', async () => {
        const { revisions, queue, app } = mk(undefined, { withAuth: true })
        await seedPosthogApp(revisions, 'sesstrim')
        const run = await request(app)
            .post('/agents/sesstrim/run')
            .set('Authorization', `Bearer ${OWNER_TOKEN}`)
            .send({ message: 'one' })
        const sid = run.body.session_id
        await queue.appendConversation(sid, {
            role: 'assistant',
            content: [{ type: 'text', text: 'two' }],
            timestamp: Date.now(),
        })
        const res = await request(app)
            .get(`/agents/sesstrim/sessions/${sid}?last_n=1`)
            .set('Authorization', `Bearer ${OWNER_TOKEN}`)
        expect(res.status).toBe(200)
        expect(res.body.conversation).toHaveLength(1)
        expect(res.body.conversation_trimmed).toBe(true)
        expect(res.body.conversation_total_turns).toBe(2)
    })

    it('GET /approvals/:id returns a queued principal approval for the owner', async () => {
        const { revisions, approvals, app } = mk(undefined, { withAuth: true })
        const { app: seeded, rev } = await seedPosthogApp(revisions, 'appr')
        const run = await request(app)
            .post('/agents/appr/run')
            .set('Authorization', `Bearer ${OWNER_TOKEN}`)
            .send({ message: 'do it' })
        const id = await queueApproval(approvals, {
            sessionId: run.body.session_id,
            appId: seeded.id,
            revId: rev.id,
            type: 'principal',
        })
        const res = await request(app).get(`/agents/appr/approvals/${id}`).set('Authorization', `Bearer ${OWNER_TOKEN}`)
        expect(res.status).toBe(200)
        expect(res.body.id).toBe(id)
        expect(res.body.tool_name).toBe('danger')
        expect(res.body.approver_scope).toEqual({ type: 'principal', allow_edit: false })
    })

    it('GET /approvals/:id refuses an anonymous (public-auth) caller', async () => {
        const { revisions, approvals, app } = mk()
        const { app: seeded, rev } = await seedApp(revisions, 'pubappr')
        const run = await request(app).post('/agents/pubappr/run').send({ message: 'do it' })
        const id = await queueApproval(approvals, {
            sessionId: run.body.session_id,
            appId: seeded.id,
            revId: rev.id,
            type: 'principal',
        })
        const res = await request(app).get(`/agents/pubappr/approvals/${id}`)
        expect(res.status).toBe(403)
        expect(res.body.error).toBe('forbidden')
    })

    it('GET /approvals/:id 404s an agent-scope row (console-only surface)', async () => {
        const { revisions, approvals, app } = mk(undefined, { withAuth: true })
        const { app: seeded, rev } = await seedPosthogApp(revisions, 'appragent')
        const run = await request(app)
            .post('/agents/appragent/run')
            .set('Authorization', `Bearer ${OWNER_TOKEN}`)
            .send({ message: 'do it' })
        const id = await queueApproval(approvals, {
            sessionId: run.body.session_id,
            appId: seeded.id,
            revId: rev.id,
            type: 'agent',
        })
        const res = await request(app)
            .get(`/agents/appragent/approvals/${id}`)
            .set('Authorization', `Bearer ${OWNER_TOKEN}`)
        expect(res.status).toBe(404)
    })
})
