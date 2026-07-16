/**
 * Full hermetic e2e of EDGE ADMISSION through the real ingress + worker + PG +
 * the real `dogs` IdP; only the model is scripted.
 *
 * An agent declares `authoritative_provider: dogs`. A Slack user mentions it:
 *   1. unbound → the ingress returns auth_required and runs NO session
 *   2. the user completes OAuth (browser → /link/dogs/callback → admission writes
 *      a canonical identity + transport binding)
 *   3. next mention → admitted → the agent actually runs and replies
 *
 * Plus a passthrough agent (no authoritative_provider) that runs immediately,
 * proving backward-compatibility through the same path.
 *
 * The second describe proves the same gate is transport-agnostic: the chat/HTTP
 * path returns the auth block as `401 { auth_required }` (jwt principals link
 * like Slack ones do), and a per-request PostHog bearer satisfies a
 * `kind: posthog` authoritative provider with no link round-trip at all.
 */

import { createHmac } from 'node:crypto'
import request from 'supertest'
import { afterEach, beforeAll, describe, expect, it } from 'vitest'

import {
    type AuthProvider,
    jwtVerifier,
    type PosthogIdentityIntrospector,
    posthogVerifier,
    type TeamOrgLookup,
} from '@posthog/agent-ingress'
import { canonicalKind, HttpClient, PgTransportBindingStore } from '@posthog/agent-shared'

import { buildCluster, Cluster, fauxText } from '../harness'
import { DogServer, startDogServer } from '../harness/dog-oauth-server'

const TEST_DB_URL =
    process.env.AGENT_TEST_DB_URL ?? 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue_test'
const SLACK_SECRET = 'test-slack-secret'
const SLACK_ENV = { SLACK_SIGNING_SECRET: SLACK_SECRET, SLACK_BOT_TOKEN: 'xoxb-test' }

async function reachable(): Promise<boolean> {
    const { Pool } = await import('pg')
    const probe = new Pool({ connectionString: TEST_DB_URL, max: 1 })
    try {
        await probe.query('SELECT 1')
        return true
    } catch {
        return false
    } finally {
        await probe.end().catch(() => undefined)
    }
}

// Swallow slack.com (the auth-link DM); pass the dog IdP/API through for real.
function recorderHttp(): { fetch: HttpClient['fetch'] } {
    const real = new HttpClient()
    return {
        fetch: (input, init) => {
            const url = typeof input === 'string' ? input : input.toString()
            if (url.includes('slack.com/api/')) {
                return Promise.resolve(new Response(JSON.stringify({ ok: true, ts: '1.0' }), { status: 200 }))
            }
            return real.fetch(input, init)
        },
    }
}

function slackMention(opts: { text: string; ts: string; thread_ts?: string; user?: string }): Record<string, unknown> {
    return {
        type: 'event_callback',
        event_id: `Ev_${opts.ts}`,
        team_id: 'T_DOGS',
        event: {
            type: 'app_mention',
            channel: 'C01',
            user: opts.user ?? 'U_ALICE',
            text: opts.text,
            ts: opts.ts,
            thread_ts: opts.thread_ts,
            team: 'T_DOGS',
        },
    }
}

function assistantText(conversation: unknown[]): string {
    const parts: string[] = []
    for (const m of conversation as Array<{ role?: string; content?: unknown }>) {
        if (m.role !== 'assistant') {
            continue
        }
        if (typeof m.content === 'string') {
            parts.push(m.content)
        } else if (Array.isArray(m.content)) {
            for (const b of m.content as Array<{ type?: string; text?: string }>) {
                if (b.type === 'text' && b.text) {
                    parts.push(b.text)
                }
            }
        }
    }
    return parts.join('\n')
}

const maybeDescribe = process.env.SKIP_PG_TESTS === '1' ? describe.skip : describe

// Drive the real OAuth callback on the ingress route: browser hits the IdP
// /authorize (302 → our callback), then GET /link/dogs/callback?state&code.
async function completeLink(c: Cluster, authorizeUrl: string): Promise<void> {
    const res = await fetch(authorizeUrl, { redirect: 'manual' })
    const loc = new URL(res.headers.get('location') ?? '')
    await request(c.ingress)
        .get(loc.pathname)
        .query({ state: loc.searchParams.get('state') ?? '', code: loc.searchParams.get('code') ?? '' })
        .expect(200)
}

maybeDescribe('edge admission e2e (Slack, authoritative provider, mocked inference)', () => {
    let ok = false
    let dog: DogServer
    let c: Cluster

    beforeAll(async () => {
        ok = await reachable()
    })

    afterEach(async () => {
        await c?.teardown().catch(() => undefined)
        await dog?.close().catch(() => undefined)
    })

    it('Slack: unbound → auth_required (no run) → link → admitted → agent runs', async () => {
        if (!ok) {
            return
        }
        dog = await startDogServer({ userSub: 'alice-canonical' })
        c = await buildCluster({ http: recorderHttp() })
        await c.deployAgent({
            slug: 'gatedbot',
            spec: {
                triggers: [{ type: 'slack', config: { trusted_workspaces: '*' } }],
                authoritative_provider: 'dogs',
                identity_providers: [
                    {
                        kind: 'oauth2',
                        id: 'dogs',
                        authorize_url: dog.authorizeUrl,
                        token_url: dog.tokenUrl,
                        userinfo_url: dog.userinfoUrl, // lets dogs prove a subject
                        client_id: 'dogs-client',
                        scopes: ['read:dog'],
                    },
                ],
            },
            encrypted_env: SLACK_ENV,
        })

        // Turn 1: unbound → auth_required, NO session enqueued.
        c.setScript([fauxText('should not run yet')])
        const first = await c.slackPost(
            'gatedbot',
            'events',
            slackMention({ text: '<@U0BOT> hi', ts: '100.0' }),
            SLACK_SECRET
        )
        expect(first.body.auth_required).toBe(true)
        expect(first.body.provider).toBe('dogs')
        expect(first.body.session_id).toBeUndefined()
        const authorizeUrl = first.body.authorize_url as string
        expect(authorizeUrl).toContain(dog.baseUrl)
        // The callback the IdP bounces back to must be the configured ingress
        // base, not a hardcoded fallback host — this is what broke when the base
        // was unset in prod.
        expect(new URL(authorizeUrl).searchParams.get('redirect_uri')).toBe('http://callback.test/link/dogs/callback')
        await c.drain() // nothing queued; a no-op

        // Complete the link → admission writes the binding + canonical identity.
        await completeLink(c, authorizeUrl)
        const bindings = new PgTransportBindingStore(c.pool)

        // Turn 2: same user → admitted → the agent actually runs and replies.
        c.setScript([fauxText('woof, how can I help?')])
        const second = await c.slackPost(
            'gatedbot',
            'events',
            slackMention({ text: '<@U0BOT> still there?', ts: '101.0', thread_ts: '100.0' }),
            SLACK_SECRET
        )
        expect(second.body.auth_required).toBeUndefined()
        expect(second.body.session_id).toBeTruthy()
        await c.drain()

        const s2 = await c.queue.get(second.body.session_id)
        expect(s2).toBeTruthy()
        expect(assistantText(s2!.conversation)).toContain('woof')

        // A transport binding now exists for this app/canonical identity.
        const cano = await c.identities.find({
            application_id: s2!.application_id,
            principal_kind: canonicalKind('dogs'),
            principal_id: 'alice-canonical',
        })
        expect(cano).toBeTruthy()
        const all = await bindings.listForCanonical(s2!.application_id, cano!.id)
        expect(all.length).toBeGreaterThanOrEqual(1)
    })

    it('passthrough: no authoritative_provider → the agent runs immediately', async () => {
        if (!ok) {
            return
        }
        dog = await startDogServer()
        c = await buildCluster({ http: recorderHttp() })
        await c.deployAgent({
            slug: 'openbot',
            spec: { triggers: [{ type: 'slack', config: { trusted_workspaces: '*' } }] },
            encrypted_env: SLACK_ENV,
        })
        c.setScript([fauxText('hello right away')])
        const res = await c.slackPost(
            'openbot',
            'events',
            slackMention({ text: '<@U0BOT> hi', ts: '200.0' }),
            SLACK_SECRET
        )
        expect(res.body.auth_required).toBeUndefined()
        expect(res.body.session_id).toBeTruthy()
        await c.drain()
        const s = await c.queue.get(res.body.session_id)
        expect(assistantText(s!.conversation)).toContain('hello right away')
    })
})

const JWT_SECRET_REF = 'EMBED_SECRET'
const JWT_SECRET_VALUE = 'chat-admission-jwt-secret'

function makeJwt(sub: string): string {
    const b64 = (v: object): string =>
        Buffer.from(JSON.stringify(v)).toString('base64').replace(/=+$/, '').replace(/\+/g, '-').replace(/\//g, '_')
    const header = b64({ alg: 'HS256', typ: 'JWT' })
    const payload = b64({ sub })
    const sig = createHmac('sha256', JWT_SECRET_VALUE)
        .update(`${header}.${payload}`)
        .digest('base64')
        .replace(/=+$/, '')
        .replace(/\+/g, '-')
        .replace(/\//g, '_')
    return `${header}.${payload}.${sig}`
}

const jwtAuthProvider: AuthProvider = {
    verifiers: [
        jwtVerifier({
            async resolve(ref) {
                return ref === JWT_SECRET_REF ? JWT_SECRET_VALUE : null
            },
        }),
    ],
}

// `project`-audience agents never consult the org lookup.
const teamOrg: TeamOrgLookup = {
    async orgForTeam() {
        return null
    },
}

const PH_SUB = 'ph-user-uuid-1'
const PH_BEARER = 'phx_live_bearer'

const posthogIntrospector: PosthogIdentityIntrospector = {
    async introspect(bearer) {
        return bearer === PH_BEARER ? { uuid: PH_SUB, email: 'alice@posthog.com', team: { id: 1 } } : null
    },
    async canAccessTeam(bearer) {
        return bearer === PH_BEARER
    },
}

// Real HTTP everywhere (the dogs IdP is a real local server), except PostHog's
// /oauth/userinfo/ — there is no Django in the harness, so the authoritative
// posthog provider's `verifyBearer` introspection is scripted by token.
function posthogUserinfoHttp(validBearers: Record<string, string>): { fetch: HttpClient['fetch'] } {
    const real = new HttpClient()
    return {
        fetch: (input, init) => {
            const url = typeof input === 'string' ? input : input.toString()
            if (url.includes('/oauth/userinfo')) {
                const auth = ((init?.headers ?? {}) as Record<string, string>)['Authorization'] ?? ''
                const sub = validBearers[auth.replace('Bearer ', '')]
                if (!sub) {
                    return Promise.resolve(new Response(JSON.stringify({ error: 'invalid_token' }), { status: 401 }))
                }
                return Promise.resolve(
                    new Response(JSON.stringify({ sub }), {
                        status: 200,
                        headers: { 'content-type': 'application/json' },
                    })
                )
            }
            return real.fetch(input, init)
        },
    }
}

maybeDescribe('edge admission e2e (chat/HTTP, authoritative provider, mocked inference)', () => {
    let ok = false
    let dog: DogServer
    let c: Cluster

    beforeAll(async () => {
        ok = await reachable()
    })

    afterEach(async () => {
        await c?.teardown().catch(() => undefined)
        await dog?.close().catch(() => undefined)
    })

    it('chat (jwt): /run → 401 auth_required (no session) → link → admitted → runs; unlink re-gates /send', async () => {
        if (!ok) {
            return
        }
        dog = await startDogServer({ userSub: 'alice-canonical' })
        c = await buildCluster({ http: new HttpClient(), authProvider: jwtAuthProvider })
        await c.deployAgent({
            slug: 'gatedchat',
            spec: {
                triggers: [{ type: 'chat', config: {} }],
                auth: { modes: [{ type: 'jwt', issuer_secret_ref: JWT_SECRET_REF }] },
                authoritative_provider: 'dogs',
                identity_providers: [
                    {
                        kind: 'oauth2',
                        id: 'dogs',
                        authorize_url: dog.authorizeUrl,
                        token_url: dog.tokenUrl,
                        userinfo_url: dog.userinfoUrl,
                        client_id: 'dogs-client',
                        scopes: ['read:dog'],
                    },
                ],
            },
        })
        const bearer = makeJwt('alice')

        // Turn 1: unbound → the auth block comes back IN the response (401),
        // and nothing is enqueued.
        c.setScript([fauxText('should not run yet')])
        const first = await request(c.ingress)
            .post('/agents/gatedchat/run')
            .set('Authorization', `Bearer ${bearer}`)
            .send({ message: 'hi' })
        expect(first.status).toBe(401)
        expect(first.body).toMatchObject({ error: 'auth_required', auth_required: true, provider: 'dogs' })
        expect(first.body.session_id).toBeUndefined()
        expect(first.body.authorize_url).toContain(dog.baseUrl)
        await c.drain() // nothing queued; a no-op

        await completeLink(c, first.body.authorize_url as string)

        // Turn 2: same JWT sub → admitted → the agent runs; the response
        // principal carries the canonical identity admission resolved.
        c.setScript([fauxText('woof, admitted')])
        const second = await request(c.ingress)
            .post('/agents/gatedchat/run')
            .set('Authorization', `Bearer ${bearer}`)
            .send({ message: 'still there?' })
        expect(second.status).toBe(200)
        await c.drain()
        const session = await c.queue.get(second.body.session_id)
        expect(assistantText(session!.conversation)).toContain('woof, admitted')

        const cano = await c.identities.find({
            application_id: session!.application_id,
            principal_kind: canonicalKind('dogs'),
            principal_id: 'alice-canonical',
        })
        expect(cano).toBeTruthy()
        expect(second.body.principal.canonical_agent_user_id).toBe(cano!.id)

        // Unlink → the binding is gone, so even the EXISTING session stops
        // advancing: /send re-runs admission per message, like the Slack path.
        const transportUser = await c.identities.find({
            application_id: session!.application_id,
            principal_kind: 'jwt',
            principal_id: 'alice',
        })
        await new PgTransportBindingStore(c.pool).unbind(session!.application_id, transportUser!.id)
        const send = await request(c.ingress)
            .post('/agents/gatedchat/send')
            .set('Authorization', `Bearer ${bearer}`)
            .send({ session_id: second.body.session_id, message: 'one more thing' })
        expect(send.status).toBe(401)
        expect(send.body.auth_required).toBe(true)
    })

    it('chat (posthog): a per-request posthog bearer satisfies a posthog authoritative provider — no link round-trip', async () => {
        if (!ok) {
            return
        }
        c = await buildCluster({
            http: posthogUserinfoHttp({ [PH_BEARER]: PH_SUB }),
            authProvider: { verifiers: [posthogVerifier(posthogIntrospector, teamOrg)] },
        })
        await c.deployAgent({
            slug: 'phgated',
            spec: {
                triggers: [{ type: 'chat', config: {} }],
                auth: { modes: [{ type: 'posthog' }] },
                authoritative_provider: 'posthog',
                // client_id is normally backend-injected on promote.
                identity_providers: [{ kind: 'posthog', id: 'posthog', client_id: 'provisioned-client' }],
            },
        })

        c.setScript([fauxText('hello, verified user')])
        const res = await request(c.ingress)
            .post('/agents/phgated/run')
            .set('Authorization', `Bearer ${PH_BEARER}`)
            .send({ message: 'hi' })
        expect(res.status).toBe(200)
        expect(res.body.auth_required).toBeUndefined()
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(assistantText(session!.conversation)).toContain('hello, verified user')

        // The bearer proved the subject inline: canonical identity + binding
        // exist without any OAuth link having run.
        const cano = await c.identities.find({
            application_id: session!.application_id,
            principal_kind: canonicalKind('posthog'),
            principal_id: PH_SUB,
        })
        expect(cano).toBeTruthy()
        expect(res.body.principal.canonical_agent_user_id).toBe(cano!.id)
        const bindings = await new PgTransportBindingStore(c.pool).listForCanonical(session!.application_id, cano!.id)
        expect(bindings).toHaveLength(1)
    })
})
