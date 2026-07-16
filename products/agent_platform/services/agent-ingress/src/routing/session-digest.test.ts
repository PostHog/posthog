/**
 * Unit tests for the internal `POST /internal/session-digest` route (see
 * server.ts). Unlike the sibling `server.test.ts` (which drives the full
 * routing surface against a real Postgres queue), this route reads a single
 * session via `queue.getForApplication` and needs no other store, so we wire
 * an in-memory fake queue and never touch the DB. That keeps these payload-
 * safety / cursor / truncation assertions fast and hermetic — exactly the
 * cases where a real DB adds nothing.
 */

import request from 'supertest'
import { describe, expect, it } from 'vitest'

import {
    type AgentSession,
    type ConversationMessage,
    type CredentialBroker,
    EMPTY_USAGE_TOTAL,
    INTERNAL_JWT_AUDIENCE,
    mintInternalJwt,
    type RevisionStore,
    type SessionEventBus,
    type SessionQueue,
} from '@posthog/agent-shared'

import { buildApp } from './server'

const SIGNING_KEY = 'test-internal-signing-key'
const APP_ID = 'app-1111-2222'
const OTHER_APP_ID = 'app-9999-8888'
const SESSION_ID = 'sess-aaaa-bbbb'

// A sentinel we plant inside a tool RESULT's content. The digest must never
// echo tool arguments or result payloads, so this string must not appear in
// any response body — that's the payload-safety property under test.
const SECRET_PAYLOAD = 'SUPER_SECRET_TOOL_OUTPUT_a1b2c3d4'

/** Minimal AgentSession fixture. Only the fields the digest route reads
 *  (`id`, `state`, `conversation`, `usage_total`) carry meaning; the rest are
 *  filled to satisfy the type. */
function makeSession(overrides: Partial<AgentSession> = {}): AgentSession {
    return {
        id: SESSION_ID,
        application_id: APP_ID,
        revision_id: 'rev-1',
        team_id: 1,
        external_key: null,
        idempotency_key: null,
        trigger_metadata: null,
        state: 'running',
        principal: null,
        conversation: [],
        pending_inputs: [],
        retry_count: 0,
        usage_total: { ...EMPTY_USAGE_TOTAL },
        acl: [],
        pending_elevation_requests: [],
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        ...overrides,
    } as AgentSession
}

/** In-memory queue whose `getForApplication` honours the (session_id,
 *  application_id) tenant scope exactly like the Pg store — returning null when
 *  the ids don't both match, so the cross-tenant 404 test is meaningful. */
function fakeQueue(session: AgentSession | null): SessionQueue {
    return {
        async getForApplication(sessionId: string, applicationId: string): Promise<AgentSession | null> {
            if (!session) {
                return null
            }
            if (sessionId === session.id && applicationId === session.application_id) {
                return session
            }
            return null
        },
    } as unknown as SessionQueue
}

/** Build the ingress app with a fake queue + internal signing key. No other
 *  store is exercised by the digest route, so they're stubbed. */
function mk(session: AgentSession | null): ReturnType<typeof buildApp> {
    return buildApp({
        revisions: {} as unknown as RevisionStore,
        queue: fakeQueue(session),
        bus: {} as unknown as SessionEventBus,
        credentialBroker: {} as unknown as CredentialBroker,
        routingMode: 'path',
        pathPrefix: '/agents',
        internalSigningKey: SIGNING_KEY,
    })
}

/** Same as mk but with NO internal signing key — the route shares the public
 *  listener, so a missing key must fail closed (500), never open the door. */
function mkNoKey(session: AgentSession | null): ReturnType<typeof buildApp> {
    return buildApp({
        revisions: {} as unknown as RevisionStore,
        queue: fakeQueue(session),
        bus: {} as unknown as SessionEventBus,
        credentialBroker: {} as unknown as CredentialBroker,
        routingMode: 'path',
        pathPrefix: '/agents',
        internalSigningKey: undefined,
    })
}

async function ingressToken(): Promise<string> {
    return mintInternalJwt({ audience: INTERNAL_JWT_AUDIENCE.INGRESS_RPC, signingKey: SIGNING_KEY })
}

function user(content: string): ConversationMessage {
    return { role: 'user', content, timestamp: Date.now() }
}

function assistantText(text: string): ConversationMessage {
    return { role: 'assistant', content: [{ type: 'text', text }], timestamp: Date.now() }
}

function assistantToolCall(name: string, args: Record<string, unknown>): ConversationMessage {
    return {
        role: 'assistant',
        content: [{ type: 'toolCall', id: `call-${name}`, name, arguments: args }],
        timestamp: Date.now(),
    }
}

function toolResult(toolName: string, text: string, isError = false): ConversationMessage {
    return {
        role: 'toolResult',
        toolCallId: `call-${toolName}`,
        toolName,
        content: [{ type: 'text', text }],
        isError,
        timestamp: Date.now(),
    }
}

describe('POST /internal/session-digest', () => {
    it('401s {missing_token} when x-internal-secret is absent', async () => {
        const app = mk(makeSession())
        const res = await request(app)
            .post('/internal/session-digest')
            .send({ application_id: APP_ID, session_id: SESSION_ID })
        expect(res.status).toBe(401)
        expect(res.body).toEqual({ error: 'unauthorized', reason: 'missing_token' })
    })

    it('500s {internal_auth_not_configured} when no internal signing key is set (fail closed)', async () => {
        // The route shares the public listener; a missing key is a misconfig, not
        // an open door — it must 500 before even looking at the token.
        const app = mkNoKey(makeSession())
        const token = await ingressToken()
        const res = await request(app)
            .post('/internal/session-digest')
            .set('x-internal-secret', token)
            .send({ application_id: APP_ID, session_id: SESSION_ID })
        expect(res.status).toBe(500)
        expect(res.body).toEqual({ error: 'internal_auth_not_configured' })
    })

    it('400s {invalid_body} when a required field is missing (valid token)', async () => {
        // Auth passes, but the body omits session_id → schema rejection, not a 500.
        const app = mk(makeSession())
        const token = await ingressToken()
        const res = await request(app)
            .post('/internal/session-digest')
            .set('x-internal-secret', token)
            .send({ application_id: APP_ID })
        expect(res.status).toBe(400)
        expect(res.body.error).toBe('invalid_body')
    })

    it('401s a wrong-audience JWT (minted for JANITOR_RPC)', async () => {
        const app = mk(makeSession())
        const wrongAud = await mintInternalJwt({
            audience: INTERNAL_JWT_AUDIENCE.JANITOR_RPC,
            signingKey: SIGNING_KEY,
        })
        const res = await request(app)
            .post('/internal/session-digest')
            .set('x-internal-secret', wrongAud)
            .send({ application_id: APP_ID, session_id: SESSION_ID })
        expect(res.status).toBe(401)
        expect(res.body.error).toBe('unauthorized')
    })

    it('404s {session_not_found} when the session belongs to a DIFFERENT application (no cross-tenant leak)', async () => {
        // The session exists under APP_ID; a caller scoped to OTHER_APP_ID must
        // get an indistinguishable "not found", never the session's existence.
        const app = mk(makeSession())
        const token = await ingressToken()
        const res = await request(app)
            .post('/internal/session-digest')
            .set('x-internal-secret', token)
            .send({ application_id: OTHER_APP_ID, session_id: SESSION_ID })
        expect(res.status).toBe(404)
        expect(res.body).toEqual({ error: 'session_not_found' })
    })

    it('happy path: digest names the tool + its byte count, never the payload; terminal → done', async () => {
        const conversation: ConversationMessage[] = [
            user('run the report'),
            assistantToolCall('run_query', { sql: 'SELECT * FROM secret_table' }),
            toolResult('run_query', SECRET_PAYLOAD),
            assistantText('Here is your report summary.'),
        ]
        const app = mk(makeSession({ state: 'completed', conversation }))
        const token = await ingressToken()
        const res = await request(app)
            .post('/internal/session-digest')
            .set('x-internal-secret', token)
            .send({ application_id: APP_ID, session_id: SESSION_ID })
        expect(res.status).toBe(200)
        expect(res.body.session_id).toBe(SESSION_ID)
        expect(res.body.next_cursor).toBe(conversation.length)
        expect(res.body.turns).toBe(conversation.length)
        // `completed` is terminal → done true.
        expect(res.body.done).toBe(true)
        // Digest carries the last assistant text + the tool-activity line.
        expect(res.body.digest).toContain('Here is your report summary.')
        expect(res.body.digest).toContain('run_query')
        // A byte-count marker (`NB`) is present for the tool result.
        expect(res.body.digest).toMatch(/run_query[^;]*\b\d+B\b/)
        // Payload safety: neither the tool ARGUMENTS nor the RESULT payload text
        // leak into any part of the response.
        const whole = JSON.stringify(res.body)
        expect(whole).not.toContain(SECRET_PAYLOAD)
        expect(whole).not.toContain('secret_table')
    })

    it('non-terminal running session reports done:false', async () => {
        const app = mk(makeSession({ state: 'running', conversation: [assistantText('working…')] }))
        const token = await ingressToken()
        const res = await request(app)
            .post('/internal/session-digest')
            .set('x-internal-secret', token)
            .send({ application_id: APP_ID, session_id: SESSION_ID })
        expect(res.status).toBe(200)
        expect(res.body.done).toBe(false)
    })

    it('cursor: tool activity reflects only conversation[cursor:]; re-poll at next_cursor yields no tool activity', async () => {
        // First 2 turns hold the tool traffic; a later assistant turn follows.
        const conversation: ConversationMessage[] = [
            assistantToolCall('search', {}),
            toolResult('search', 'first batch of rows'),
            assistantText('done searching'),
        ]
        const app = mk(makeSession({ conversation }))
        const token = await ingressToken()
        // cursor=2 → slice is just the trailing assistant text, no tool activity.
        const res = await request(app)
            .post('/internal/session-digest')
            .set('x-internal-secret', token)
            .send({ application_id: APP_ID, session_id: SESSION_ID, cursor: 2 })
        expect(res.status).toBe(200)
        expect(res.body.digest).toContain('Tools: (none)')
        expect(res.body.digest).not.toContain('search ×')
        // Re-poll from the returned next_cursor (== length): empty slice, still no
        // tool activity, no double-serve of the earlier tool traffic.
        const next = res.body.next_cursor as number
        expect(next).toBe(conversation.length)
        const res2 = await request(app)
            .post('/internal/session-digest')
            .set('x-internal-secret', token)
            .send({ application_id: APP_ID, session_id: SESSION_ID, cursor: next })
        expect(res2.status).toBe(200)
        expect(res2.body.digest).toContain('Tools: (none)')
        expect(res2.body.next_cursor).toBe(conversation.length)
    })

    it('max_chars: a large conversation clips to <= max_chars code points with a re-poll pointer', async () => {
        const bigText = 'x'.repeat(5_000)
        const conversation: ConversationMessage[] = [assistantText(bigText)]
        const app = mk(makeSession({ conversation }))
        const token = await ingressToken()
        const MAX = 200
        const res = await request(app)
            .post('/internal/session-digest')
            .set('x-internal-secret', token)
            .send({ application_id: APP_ID, session_id: SESSION_ID, max_chars: MAX })
        expect(res.status).toBe(200)
        expect(res.body.truncated).toBe(true)
        // Code-point length (not UTF-16 length) is what the route budgets against.
        expect(Array.from(res.body.digest as string).length).toBeLessThanOrEqual(MAX)
        expect(res.body.digest).toContain('…[digest clipped; re-poll with cursor=')
    })

    it('max_chars smaller than the re-poll pointer still never exceeds max_chars', async () => {
        const conversation: ConversationMessage[] = [assistantText('x'.repeat(5_000))]
        const app = mk(makeSession({ conversation }))
        const token = await ingressToken()
        const MAX = 10 // smaller than the ~40-char pointer — the hard cap must win
        const res = await request(app)
            .post('/internal/session-digest')
            .set('x-internal-secret', token)
            .send({ application_id: APP_ID, session_id: SESSION_ID, max_chars: MAX })
        expect(res.status).toBe(200)
        expect(res.body.truncated).toBe(true)
        expect(Array.from(res.body.digest as string).length).toBeLessThanOrEqual(MAX)
    })
})
