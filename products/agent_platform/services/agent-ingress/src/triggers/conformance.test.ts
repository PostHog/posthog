/**
 * Trigger-module conformance suite.
 *
 * Every `TRIGGER_MODULES` entry re-implements the same edges (signature
 * verification, content-type robustness, untrusted-vs-broken sender, redelivery
 * dedup); this encodes that contract once against the real HTTP surface so a new
 * trigger must satisfy it explicitly. `CONFORMANCE_FIXTURES` is the source of
 * truth for which edge classes apply to which trigger.
 *
 * Auth enforcement (declared kind == enforced kind) is covered by
 * agent-tests/src/cases/auth-contract.test.ts; this suite owns edge semantics —
 * what happens once a request clears (or deliberately fails) that gate.
 */

import { createHmac, randomUUID } from 'crypto'
import { Express } from 'express'
import { Pool } from 'pg'
import request from 'supertest'
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import {
    AgentApplication,
    AgentRevision,
    AgentSession,
    AgentSpecSchema,
    PgApprovalStore,
    PgCredentialBroker,
    PgRevisionStore,
    PgSessionQueue,
    RedisSessionEventBus,
    SecretResolver,
} from '@posthog/agent-shared'
import { reset } from '@posthog/agent-shared/testing'

import { buildApp, TRIGGER_MODULES } from '../routing/server'
import { encodeElevationActionValue } from './slack'
import type { TriggerType } from './types'

const TEST_DB_URL =
    process.env.AGENT_TEST_DB_URL ?? 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue_test'
// nosemgrep: trailofbits.generic.redis-unencrypted-transport.redis-unencrypted-transport
const REDIS_URL = process.env.REDIS_URL ?? 'redis://localhost:6379'
const HARNESS_ENCRYPTION_SALT_KEYS = '01234567890123456789012345678901'
const SLACK_SECRET = 'conformance-slack-secret'

const PUBLIC_AUTH = { modes: [{ type: 'public' as const, acknowledge_public_exposure: true as const }] }

/** An HTTP request the harness fires verbatim — headers/body come from the fixture and are never mutated, so a fixture-set signature or Content-Type survives untouched. */
interface RawRequest {
    path: string
    headers: Record<string, string>
    rawBody: string
}

interface DeployedTrigger {
    application: AgentApplication
    revision: AgentRevision
}

/**
 * One trigger's conformance contract. Optional fields are edge classes the
 * trigger opts into by declaring them, letting the assertions below iterate
 * generically instead of hardcoding trigger names.
 */
interface ConformanceFixture {
    type: TriggerType
    /** Deploy a fresh agent wired only for this trigger's happy path (public
     *  auth, permissive allowlist where applicable). */
    deployHappy(): Promise<DeployedTrigger>
    /** A valid, fully-authenticated request for a fresh event tagged by
     *  `nonce` — reused across edge classes to build a "this should work"
     *  baseline before perturbing one axis at a time. */
    validRequest(dep: DeployedTrigger, nonce: string): RawRequest
    /** Pull the enqueued/resumed session id out of a successful response body. */
    sessionIdFromResponse(body: unknown): string | undefined
    /** Normalize a session's seed message to a string for comparison. */
    contentOf(session: AgentSession): string
    /** The SAME logical event as `validRequest`, but mislabeled with a
     *  mismatched Content-Type (JSON sent as `application/x-www-form-urlencoded`).
     *  Omitted only for a route whose natural transport already IS urlencoded
     *  (the slack-interactivity case). */
    mislabeledRequest?(dep: DeployedTrigger, nonce: string): RawRequest
    /** The EXACT seed a correct parse of `mislabeledRequest` produces. Exact,
     *  not substring: Express's urlencoded mis-parse yields a garbage object
     *  that, re-stringified into a seed, still CONTAINS the nonce — only exact
     *  equality catches the garbled-but-still-2xx shape. */
    expectedContentAfterMislabel?(nonce: string): string
    /** Signature verification. Declared only by triggers whose auth is a
     *  computed signature over the raw body (today: slack). */
    signing?: {
        /** Build a request signed with `secret` — pass the real secret for a
         *  "missing secret resolver" probe, or a wrong one for an "invalid
         *  signature" probe. */
        request(dep: DeployedTrigger, nonce: string, secret: string): RawRequest
    }
    /** A secondary trust gate evaluated AFTER auth succeeds (today: slack's
     *  `trusted_workspaces`). Declared only by triggers that have one. */
    allowlist?: {
        /** Deploy an agent whose allowlist will reject the probe identity
         *  `rejectedRequest` uses. */
        deployRejecting(): Promise<DeployedTrigger>
        /** A request that authenticates/signs fine but misses the allowlist. */
        rejectedRequest(dep: DeployedTrigger, nonce: string): RawRequest
    }
    /** Redelivery dedup. Declared only by triggers with a dedup identity
     *  (a provider delivery-id header, or — for slack — the event's own
     *  (channel, ts) coordinates). */
    dedup?: {
        /** Build a request carrying the same dedup identity for a given
         *  `nonce`; calling this twice with the same nonce must collapse to
         *  one session. */
        request(dep: DeployedTrigger, nonce: string): RawRequest
    }
}

function jsonRequest(path: string, body: unknown, extraHeaders: Record<string, string> = {}): RawRequest {
    return { path, headers: { 'content-type': 'application/json', ...extraHeaders }, rawBody: JSON.stringify(body) }
}

/** Same bytes as `jsonRequest`, but the Content-Type header lies — raw body is still valid JSON. */
function mislabeledAsUrlencoded(path: string, body: unknown, extraHeaders: Record<string, string> = {}): RawRequest {
    return {
        path,
        headers: { 'content-type': 'application/x-www-form-urlencoded', ...extraHeaders },
        rawBody: JSON.stringify(body),
    }
}

function signSlackBody(rawBody: string, secret: string): { ts: string; sig: string } {
    const ts = String(Math.floor(Date.now() / 1000))
    const mac = createHmac('sha256', secret).update(`v0:${ts}:${rawBody}`).digest('hex')
    return { ts, sig: `v0=${mac}` }
}

function slackSignedRequest(path: string, bodyObj: unknown, contentType: string, secret: string): RawRequest {
    const raw = JSON.stringify(bodyObj)
    const { ts, sig } = signSlackBody(raw, secret)
    return {
        path,
        headers: { 'content-type': contentType, 'x-slack-request-timestamp': ts, 'x-slack-signature': sig },
        rawBody: raw,
    }
}

/** Seed message content is `ConversationMessage['content']`, which can be a
 *  plain string or a structured block list — normalize to a string so the
 *  content-type test can `.toContain(nonce)` regardless of shape. */
function seedContent(session: AgentSession): string {
    const content = session.conversation[0]?.content ?? ''
    return typeof content === 'string' ? content : JSON.stringify(content)
}

function slackEventBody(nonce: string, workspace: string): Record<string, unknown> {
    return {
        type: 'event_callback',
        team_id: workspace,
        event: { type: 'message', channel: `C-${nonce}`, user: 'U1', text: `hello-${nonce}`, ts: `${nonce}.000` },
    }
}

/** The exact seed slack.ts builds for a plain `message` event from
 *  `slackEventBody` (never hits the mention/DM/resume branches). Mirrors the
 *  `slackContext` template in `slack.ts`. */
function expectedSlackSeed(nonce: string, workspace: string): string {
    return [
        '[slack]',
        `channel: C-${nonce}`,
        `ts: ${nonce}.000`,
        `thread_ts: ${nonce}.000`,
        `workspace: ${workspace}`,
        'user: U1',
        'mention: false',
        'dm: false',
        '',
        `hello-${nonce}`,
    ].join('\n')
}

let pool: Pool
let bus: RedisSessionEventBus
let revisions: PgRevisionStore
let queue: PgSessionQueue
let approvals: PgApprovalStore
let credentialBroker: PgCredentialBroker
let happyApp: Express

function buildTestApp(overrides: { slackSigningSecretResolver?: SecretResolver } = {}): Express {
    return buildApp({
        revisions,
        queue,
        approvals,
        bus,
        credentialBroker,
        routingMode: 'path',
        pathPrefix: '/agents',
        slackSigningSecretResolver: overrides.slackSigningSecretResolver ?? {
            async resolve(): Promise<string | null> {
                return SLACK_SECRET
            },
        },
    })
}

async function deployAgent(triggers: unknown[]): Promise<DeployedTrigger> {
    const slug = `conformance-${randomUUID().slice(0, 12)}`
    const application = await revisions.createApplication({ team_id: 1, slug, name: slug, description: '' })
    const revision = await revisions.createRevision({
        application_id: application.id,
        parent_revision_id: null,
        created_by_id: null,
        bundle_uri: 's3://x/',
        spec: AgentSpecSchema.parse({ model: 'test/x', triggers }),
    })
    await revisions.setRevisionState(revision.id, 'live')
    await revisions.setLiveRevision(application.id, revision.id)
    return { application, revision }
}

async function fire(app: Express, req: RawRequest): Promise<request.Response> {
    let r = request(app).post(req.path)
    for (const [name, value] of Object.entries(req.headers)) {
        r = r.set(name, value)
    }
    return r.send(req.rawBody)
}

const CONFORMANCE_FIXTURES: Partial<Record<TriggerType, ConformanceFixture>> = {
    chat: {
        type: 'chat',
        async deployHappy() {
            return deployAgent([{ type: 'chat', config: {}, auth: PUBLIC_AUTH }])
        },
        validRequest(dep, nonce) {
            return jsonRequest(`/agents/${dep.application.slug}/run`, {
                message: `hello-${nonce}`,
                external_key: `chat-ext-${nonce}`,
            })
        },
        mislabeledRequest(dep, nonce) {
            return mislabeledAsUrlencoded(`/agents/${dep.application.slug}/run`, { message: `hello-${nonce}` })
        },
        // ChatRunBodySchema requires `message` as a top-level key, which urlencoded mis-parsing can't produce, so this arm 400s first (unreachable today; declared for parity).
        expectedContentAfterMislabel: (nonce) => `hello-${nonce}`,
        sessionIdFromResponse: (body) => (body as { session_id?: string }).session_id,
        contentOf: seedContent,
        // No signing (bearer auth, not a body signature), no allowlist (auth
        // IS the gate), no dedup (client picks external_key; there's no
        // provider delivery id to redeliver).
    },
    webhook: {
        type: 'webhook',
        async deployHappy() {
            return deployAgent([{ type: 'webhook', config: { path: '/webhook' }, auth: PUBLIC_AUTH }])
        },
        validRequest(dep, nonce) {
            return jsonRequest(`/agents/${dep.application.slug}/webhook`, { event: `payload-${nonce}` })
        },
        mislabeledRequest(dep, nonce) {
            return mislabeledAsUrlencoded(`/agents/${dep.application.slug}/webhook`, { event: `payload-${nonce}` })
        },
        // webhook.ts delivers the body verbatim as the first user message (JSON-stringified), so a correct parse of `{ event: ... }` produces exactly this string.
        expectedContentAfterMislabel: (nonce) => JSON.stringify({ event: `payload-${nonce}` }),
        sessionIdFromResponse: (body) => (body as { session_id?: string }).session_id,
        contentOf: seedContent,
        // No allowlist knob — auth is the only gate webhook has.
        dedup: {
            request(dep, nonce) {
                // `X-GitHub-Delivery` is one of the provider delivery-id
                // headers webhook.ts keys dedup on.
                return jsonRequest(
                    `/agents/${dep.application.slug}/webhook`,
                    { event: `dedup-${nonce}` },
                    { 'x-github-delivery': `gh-${nonce}` }
                )
            },
        },
    },
    mcp: {
        type: 'mcp',
        async deployHappy() {
            return deployAgent([{ type: 'mcp', config: {}, auth: PUBLIC_AUTH }])
        },
        validRequest(dep, nonce) {
            return jsonRequest(`/agents/${dep.application.slug}/mcp`, {
                jsonrpc: '2.0',
                id: 1,
                method: 'tools/call',
                params: { name: 'ask', arguments: { message: `hello-${nonce}` } },
            })
        },
        mislabeledRequest(dep, nonce) {
            return mislabeledAsUrlencoded(`/agents/${dep.application.slug}/mcp`, {
                jsonrpc: '2.0',
                id: 1,
                method: 'tools/call',
                params: { name: 'ask', arguments: { message: `hello-${nonce}` } },
            })
        },
        // McpRequestBodySchema requires `jsonrpc`/`method` as top-level keys, which urlencoded mis-parsing can't produce, so this arm 400s first (unreachable; declared for parity).
        expectedContentAfterMislabel: (nonce) => `hello-${nonce}`,
        sessionIdFromResponse(body) {
            const rpc = body as { result?: { content?: Array<{ text?: string }> } }
            const text = rpc.result?.content?.[0]?.text
            if (!text) {
                return undefined
            }
            try {
                return (JSON.parse(text) as { session_id?: string }).session_id
            } catch {
                return undefined
            }
        },
        contentOf: seedContent,
        // No signing, no allowlist, no dedup — MCP has no provider
        // delivery-id concept; session continuation is client-driven.
    },
    slack: {
        type: 'slack',
        async deployHappy() {
            return deployAgent([{ type: 'slack', config: { trusted_workspaces: '*' } }])
        },
        validRequest(dep, nonce) {
            return slackSignedRequest(
                `/agents/${dep.application.slug}/slack/events`,
                slackEventBody(nonce, 'T-TRUSTED'),
                'application/json',
                SLACK_SECRET
            )
        },
        mislabeledRequest(dep, nonce) {
            return slackSignedRequest(
                `/agents/${dep.application.slug}/slack/events`,
                slackEventBody(nonce, 'T-TRUSTED'),
                'application/x-www-form-urlencoded',
                SLACK_SECRET
            )
        },
        expectedContentAfterMislabel: (nonce) => expectedSlackSeed(nonce, 'T-TRUSTED'),
        sessionIdFromResponse: (body) => (body as { session_id?: string }).session_id,
        contentOf: seedContent,
        signing: {
            request(dep, nonce, secret) {
                return slackSignedRequest(
                    `/agents/${dep.application.slug}/slack/events`,
                    slackEventBody(nonce, 'T-TRUSTED'),
                    'application/json',
                    secret
                )
            },
        },
        allowlist: {
            async deployRejecting() {
                return deployAgent([{ type: 'slack', config: { trusted_workspaces: ['T-ALLOWED-ONLY'] } }])
            },
            rejectedRequest(dep, nonce) {
                return slackSignedRequest(
                    `/agents/${dep.application.slug}/slack/events`,
                    slackEventBody(nonce, 'T-NOT-ALLOWED'),
                    'application/json',
                    SLACK_SECRET
                )
            },
        },
        dedup: {
            request(dep, nonce) {
                // Same nonce twice → same (channel, ts) → the same `slack:msg:<channel>:<ts>` idempotency key slack.ts computes; the dedup identity is the event envelope, not a wire header.
                return slackSignedRequest(
                    `/agents/${dep.application.slug}/slack/events`,
                    slackEventBody(nonce, 'T-TRUSTED'),
                    'application/json',
                    SLACK_SECRET
                )
            },
        },
    },
}

describe('trigger-module conformance suite', () => {
    beforeAll(async () => {
        pool = new Pool({ connectionString: TEST_DB_URL })
        bus = new RedisSessionEventBus({
            url: REDIS_URL,
            channelPrefix: `conformance_${Math.random().toString(36).slice(2, 10)}`,
        })
        await bus.connect()
        revisions = new PgRevisionStore(pool)
        queue = new PgSessionQueue(pool)
        approvals = new PgApprovalStore(pool)
        credentialBroker = new PgCredentialBroker(pool, { encryptionSaltKeys: HARNESS_ENCRYPTION_SALT_KEYS })
    })

    beforeEach(async () => {
        await reset({ databaseUrl: TEST_DB_URL })
        happyApp = buildTestApp()
    })

    afterAll(async () => {
        await bus.disconnect()
        await pool.end()
    })

    describe('fixture totality (the ratchet)', () => {
        it(`every TRIGGER_MODULES entry has a CONFORMANCE_FIXTURES entry (floor: ${TRIGGER_MODULES.length} modules)`, () => {
            // Floor first: a totality loop over an empty `TRIGGER_MODULES` passes vacuously, so pin a count floor — a registry collapsing to nothing fails here instead of silently disabling every case.
            expect(TRIGGER_MODULES.length).toBeGreaterThanOrEqual(4)
            const missing = TRIGGER_MODULES.map((m) => m.type).filter((t) => !CONFORMANCE_FIXTURES[t])
            // A newly registered trigger with no fixture shows up here by name.
            expect(missing).toEqual([])
        })
    })

    // The inner suites filter fixtures with `.filter(f => f.<edge>)`, but that
    // predicate is a hidden hand-list — a trigger that omits an edge key is
    // silently uncovered and green. Double-entry guards it: EXPECTED (below) is
    // reconciled against the fixtures both ways. `signing` is derived from the
    // live modules (a `slack_signing` route auto-appears); the bespoke edges are
    // declared explicitly, keeping "is this list complete?" a visible judgment.
    describe('edge-class membership (double-entry over the filter-predicate hand-lists)', () => {
        type EdgeKey = 'signing' | 'mislabeledRequest' | 'allowlist' | 'dedup'
        const declares = (edge: EdgeKey): Set<TriggerType> =>
            new Set(
                Object.values(CONFORMANCE_FIXTURES)
                    .filter((f): f is ConformanceFixture => Boolean(f?.[edge]))
                    .map((f) => f.type)
            )
        const EXPECTED: Record<EdgeKey, Set<TriggerType>> = {
            signing: new Set(
                TRIGGER_MODULES.filter((m) => m.routes.some((r) => r.auth === 'slack_signing')).map((m) => m.type)
            ),
            mislabeledRequest: new Set<TriggerType>(['chat', 'webhook', 'mcp', 'slack']),
            allowlist: new Set<TriggerType>(['slack']),
            dedup: new Set<TriggerType>(['webhook', 'slack']),
        }
        const edges = Object.keys(EXPECTED) as EdgeKey[]

        it.each(edges)('%s: in scope for at least one trigger (floor — never vacuous)', (edge) => {
            expect(EXPECTED[edge].size).toBeGreaterThanOrEqual(1)
        })
        it.each(edges)('%s: every trigger in scope declares a fixture (no silent under-coverage)', (edge) => {
            const missing = [...EXPECTED[edge]].filter((t) => !declares(edge).has(t))
            expect(missing, `in scope for ${edge} but no fixture declares it: ${missing.join(', ')}`).toEqual([])
        })
        it.each(edges)('%s: every fixture that declares it is in scope (no stray/misclassified case)', (edge) => {
            const stray = [...declares(edge)].filter((t) => !EXPECTED[edge].has(t))
            expect(stray, `fixture declares ${edge} but it is not classified in scope: ${stray.join(', ')}`).toEqual([])
        })
    })

    describe('signing fail-closed', () => {
        const fixtures = Object.values(CONFORMANCE_FIXTURES).filter(
            (f): f is ConformanceFixture & { signing: NonNullable<ConformanceFixture['signing']> } =>
                Boolean(f?.signing)
        )

        it.each(fixtures)('$type: unresolvable signing secret → 5xx, never a 2xx', async (fx) => {
            const dep = await fx.deployHappy()
            const unconfiguredApp = buildTestApp({
                slackSigningSecretResolver: {
                    async resolve(): Promise<string | null> {
                        return null
                    },
                },
            })
            const req = fx.signing.request(dep, randomUUID().slice(0, 8), SLACK_SECRET)
            const res = await fire(unconfiguredApp, req)
            expect(res.status).toBeGreaterThanOrEqual(500)
            expect(res.status).toBeLessThan(600)
        })

        it.each(fixtures)('$type: invalid signature → 401', async (fx) => {
            const dep = await fx.deployHappy()
            const req = fx.signing.request(dep, randomUUID().slice(0, 8), 'definitely-the-wrong-secret')
            const res = await fire(happyApp, req)
            expect(res.status).toBe(401)
            expect((res.body as { error?: string }).error).toBe('invalid_signature')
        })
    })

    describe('content-type robustness (urlencoded-mislabeled body must never silently drop)', () => {
        const fixtures = Object.values(CONFORMANCE_FIXTURES).filter(
            (
                f
            ): f is ConformanceFixture & {
                mislabeledRequest: NonNullable<ConformanceFixture['mislabeledRequest']>
                expectedContentAfterMislabel: NonNullable<ConformanceFixture['expectedContentAfterMislabel']>
            } => Boolean(f?.mislabeledRequest)
        )

        it.each(fixtures)(
            '$type: a JSON body mislabeled as application/x-www-form-urlencoded is rejected explicitly or processed correctly — never acked while dropped',
            async (fx) => {
                const dep = await fx.deployHappy()
                const nonce = randomUUID().slice(0, 8)
                const before = await queue.listByApplication(dep.application.id, { limit: 50 })
                const req = fx.mislabeledRequest(dep, nonce)
                const res = await fire(happyApp, req)
                const accepted = res.status >= 200 && res.status < 300
                if (accepted) {
                    // "process correctly" arm: assert the body was actually parsed, not just acked. Exact equality (not substring) — see `expectedContentAfterMislabel`.
                    const sessionId = fx.sessionIdFromResponse(res.body)
                    expect(sessionId).toBeTruthy()
                    const session = await queue.get(sessionId!)
                    expect(session).not.toBeNull()
                    expect(fx.contentOf(session!)).toBe(fx.expectedContentAfterMislabel(nonce))
                } else {
                    // "reject explicitly" arm: a clear 4xx naming the problem —
                    // never a 5xx (that's the trigger's own fault, not the
                    // caller's) and never a bare ack.
                    expect(res.status).toBeGreaterThanOrEqual(400)
                    expect(res.status).toBeLessThan(500)
                    expect((res.body as { error?: string })?.error).toBeTruthy()
                }
                const after = await queue.listByApplication(dep.application.id, { limit: 50 })
                expect(after.length).toBe(before.length + (accepted ? 1 : 0))
            }
        )

        // Slack's interactivity route legitimately receives `payload=<json>` as
        // urlencoded, so this is its dedicated "process correctly" arm: prove the
        // Express body-parser actually extracts `payload` (a regression would 400
        // on `missing_payload` instead of reaching the session lookup below).
        it('slack: /slack/interactivity legitimately consumes application/x-www-form-urlencoded payload=', async () => {
            const dep = await deployAgent([{ type: 'slack', config: { trusted_workspaces: '*' } }])
            const actionValue = encodeElevationActionValue({
                sessionId: randomUUID(),
                requestId: randomUUID(),
                decision: 'grant',
            })
            const payload = JSON.stringify({
                type: 'block_actions',
                team: { id: 'T-TRUSTED' },
                user: { id: 'U1', team_id: 'T-TRUSTED' },
                actions: [{ action_id: 'a', value: actionValue }],
            })
            const raw = `payload=${encodeURIComponent(payload)}`
            const { ts, sig } = signSlackBody(raw, SLACK_SECRET)
            const res = await request(happyApp)
                .post(`/agents/${dep.application.slug}/slack/interactivity`)
                .set('content-type', 'application/x-www-form-urlencoded')
                .set('x-slack-request-timestamp', ts)
                .set('x-slack-signature', sig)
                .send(raw)
            expect(res.status).toBe(404)
            expect((res.body as { error?: string }).error).toBe('session_not_found')
        })
    })

    describe('drop semantics: an authenticated event that fails an allowlist must ack 2xx with a drop indication', () => {
        const fixtures = Object.values(CONFORMANCE_FIXTURES).filter(
            (f): f is ConformanceFixture & { allowlist: NonNullable<ConformanceFixture['allowlist']> } =>
                Boolean(f?.allowlist)
        )

        it.each(fixtures)('$type: allowlist miss → 2xx ack with drop indication, never a 4xx', async (fx) => {
            const dep = await fx.allowlist.deployRejecting()
            const nonce = randomUUID().slice(0, 8)
            const before = await queue.listByApplication(dep.application.id, { limit: 50 })
            const req = fx.allowlist.rejectedRequest(dep, nonce)
            const res = await fire(happyApp, req)
            // A signed, authenticated delivery that misses an allowlist is a
            // routing decision, not a delivery failure — providers retry
            // non-2xx responses, so a 4xx here would cause redelivery storms.
            expect(res.status).toBeGreaterThanOrEqual(200)
            expect(res.status).toBeLessThan(300)
            expect((res.body as { dropped?: string }).dropped).toBeTruthy()
            const after = await queue.listByApplication(dep.application.id, { limit: 50 })
            expect(after.length).toBe(before.length)
        })
    })

    describe('dedup: a redelivered event collapses to one enqueue', () => {
        const fixtures = Object.values(CONFORMANCE_FIXTURES).filter(
            (f): f is ConformanceFixture & { dedup: NonNullable<ConformanceFixture['dedup']> } => Boolean(f?.dedup)
        )

        it.each(fixtures)('$type: the same event delivered twice → a single session', async (fx) => {
            const dep = await fx.deployHappy()
            const nonce = randomUUID().slice(0, 8)
            const first = await fire(happyApp, fx.dedup.request(dep, nonce))
            const firstSessionId = fx.sessionIdFromResponse(first.body)
            expect(firstSessionId).toBeTruthy()

            const second = await fire(happyApp, fx.dedup.request(dep, nonce))
            const secondSessionId = fx.sessionIdFromResponse(second.body)
            expect(secondSessionId).toBe(firstSessionId)

            const sessions = await queue.listByApplication(dep.application.id, { limit: 50 })
            expect(sessions).toHaveLength(1)
            const session = await queue.get(firstSessionId!)
            expect(session!.conversation).toHaveLength(1)
            expect(session!.pending_inputs).toHaveLength(0)
        })
    })
})
