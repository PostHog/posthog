/**
 * Full hermetic e2e of identity linking, Slack principal, mocked inference.
 *
 * A Slack user @-mentions an agent whose tool needs a `dogs` credential they
 * haven't linked. Real ingress + real worker + real PG + the real dogs IdP;
 * only the model is scripted. We assert the whole arc:
 *   1. unlinked → the tool returns an auth_required link
 *   2. the user completes the OAuth link (browser → callback → token exchange)
 *   3. on the next mention the tool resolves the credential and really calls
 *      the dog API as that user (200)
 *
 * Then the same arc with a JWT principal, proving the flow is principal-source
 * agnostic (Axis A).
 */

import { createHmac } from 'node:crypto'
import request from 'supertest'
import { afterEach, beforeAll, describe, expect, it } from 'vitest'

import { type AuthProvider, jwtVerifier } from '@posthog/agent-ingress'
import { EncryptedEnvSecretResolver, EncryptedFields, HttpClient } from '@posthog/agent-shared'

import { buildCluster, Cluster, fauxCallTool, fauxText } from '../harness'
import { DogServer, startDogServer } from '../harness/dog-oauth-server'

const TEST_DB_URL =
    process.env.AGENT_TEST_DB_URL ?? 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue_test'
const KEY = '01234567890123456789012345678901' // matches HARNESS_ENCRYPTION_SALT_KEYS
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

/** Recorder http: swallow slack.com (no real network), pass everything else
 *  (the dog IdP + dog API on localhost) through to a real client. */
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

function signJwt(secret: string, claims: Record<string, unknown>): string {
    const b64 = (o: unknown): string => Buffer.from(JSON.stringify(o)).toString('base64url')
    const signingInput = `${b64({ alg: 'HS256', typ: 'JWT' })}.${b64(claims)}`
    const sig = createHmac('sha256', secret).update(signingInput).digest('base64url')
    return `${signingInput}.${sig}`
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

/** Pull the parsed content of every tool-result message in the conversation. */
function toolResults(conversation: unknown[]): Array<Record<string, unknown>> {
    const out: Array<Record<string, unknown>> = []
    for (const m of conversation as Array<{ role?: string; content?: Array<{ type: string; text?: string }> }>) {
        if (m.role !== 'toolResult' || !Array.isArray(m.content)) {
            continue
        }
        for (const block of m.content) {
            if (block.type === 'text' && block.text) {
                try {
                    out.push(JSON.parse(block.text) as Record<string, unknown>)
                } catch {
                    // non-JSON tool text — skip
                }
            }
        }
    }
    return out
}

const maybeDescribe = process.env.SKIP_PG_TESTS === '1' ? describe.skip : describe

maybeDescribe('identity linking e2e (Slack + JWT, mocked inference)', () => {
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

    const identityProviders = (): Array<Record<string, unknown>> => [
        {
            kind: 'oauth2',
            id: 'dogs',
            authorize_url: dog.authorizeUrl,
            token_url: dog.tokenUrl,
            client_id: 'dogs-client',
            scopes: ['read:dog'],
        },
    ]

    // Complete the link the real way: browser hits the IdP /authorize, which
    // 302s to our callback; we drive that callback on the actual ingress route
    // (GET /link/:provider/callback) — exercising peek → rebuild provider from
    // spec+env → complete → persist, exactly as a deployed ingress does.
    const completeLink = async (authorizeUrl: string): Promise<void> => {
        const res = await fetch(authorizeUrl, { redirect: 'manual' })
        const loc = new URL(res.headers.get('location') ?? '')
        await request(c.ingress)
            .get(loc.pathname)
            .query({ state: loc.searchParams.get('state') ?? '', code: loc.searchParams.get('code') ?? '' })
            .expect(200)
    }

    it('Slack user: gated → link → authed dog API call', async () => {
        if (!ok) {
            return
        }
        dog = await startDogServer()
        c = await buildCluster({ http: recorderHttp() })
        await c.deployAgent({
            slug: 'dogbot',
            spec: {
                triggers: [{ type: 'slack', config: { trusted_workspaces: '*' } }],
                tools: [{ kind: 'native', id: '@posthog/identity-fetch' }],
                identity_providers: identityProviders(),
            },
            encrypted_env: SLACK_ENV,
        })

        // Turn 1: model calls the dog tool → unlinked → auth_required.
        c.setScript([
            fauxCallTool('@posthog/identity-fetch', { provider: 'dogs', url: dog.apiUrl }),
            fauxText('link first'),
        ])
        const first = await c.slackPost(
            'dogbot',
            'events',
            slackMention({ text: '<@U0BOT> my dogs?', ts: '100.0' }),
            SLACK_SECRET
        )
        await c.drain()

        const s1 = await c.queue.get(first.body.session_id)
        const gated = toolResults(s1!.conversation).find((r) => r.auth_required)
        expect(gated?.auth_required).toBeTruthy()
        const authorizeUrl = (gated!.auth_required as { authorize_url: string }).authorize_url
        expect(authorizeUrl).toContain(dog.baseUrl)

        // The user links (browser → callback).
        await completeLink(authorizeUrl)

        // Turn 2: same thread + user → resumes; the tool now resolves the
        // credential and really calls the dog API.
        c.setScript([fauxCallTool('@posthog/identity-fetch', { provider: 'dogs', url: dog.apiUrl }), fauxText('woof')])
        const second = await c.slackPost(
            'dogbot',
            'events',
            slackMention({ text: '<@U0BOT> again', ts: '101.0', thread_ts: '100.0' }),
            SLACK_SECRET
        )
        await c.drain()

        const s2 = await c.queue.get(second.body.session_id)
        const success = toolResults(s2!.conversation).find((r) => r.status === 200)
        expect(success).toBeTruthy()
        expect((success!.body as { breed?: string }).breed).toBe('corgi')
        // The dog API really saw an authenticated call.
        expect(dog.dogCalls.some((call) => dog.activeTokens().includes(call.token))).toBe(true)
    })

    it('JWT principal: same arc, proving principal-source agnosticism', async () => {
        if (!ok) {
            return
        }
        dog = await startDogServer()
        // Wire the jwt verifier (the harness is public-only by default) so /run
        // accepts an internal-secret-signed JWT and mints a `jwt` principal.
        const authProvider: AuthProvider = {
            verifiers: [jwtVerifier(new EncryptedEnvSecretResolver(new EncryptedFields(KEY)))],
        }
        c = await buildCluster({ http: recorderHttp(), authProvider })
        // A chat agent authenticated by an internal-secret JWT. The gate maps
        // the jwt principal to an AgentUser via the identity store, then links.
        await c.deployAgent({
            slug: 'dogchat',
            spec: {
                triggers: [{ type: 'chat', auth: { modes: [{ type: 'jwt', issuer_secret_ref: 'JWT_SECRET' }] } }],
                tools: [{ kind: 'native', id: '@posthog/identity-fetch' }],
                identity_providers: identityProviders(),
            },
            encrypted_env: { JWT_SECRET: 'jwt-issuer-secret' },
        })

        const jwt = signJwt('jwt-issuer-secret', { sub: 'alice-jwt' })
        const auth = `Bearer ${jwt}`
        c.setScript([
            fauxCallTool('@posthog/identity-fetch', { provider: 'dogs', url: dog.apiUrl }),
            fauxText('link first'),
        ])
        const run = await request(c.ingress)
            .post('/agents/dogchat/run')
            .set('Authorization', auth)
            .send({ message: 'my dogs?' })
        await c.drain()

        const s1 = await c.queue.get(run.body.session_id)
        const gated = toolResults(s1!.conversation).find((r) => r.auth_required)
        expect(gated?.auth_required).toBeTruthy()
        await completeLink((gated!.auth_required as { authorize_url: string }).authorize_url)

        c.setScript([fauxCallTool('@posthog/identity-fetch', { provider: 'dogs', url: dog.apiUrl }), fauxText('woof')])
        await request(c.ingress)
            .post('/agents/dogchat/send')
            .set('Authorization', auth)
            .send({ session_id: run.body.session_id, message: 'again' })
        await c.drain()

        const s2 = await c.queue.get(run.body.session_id)
        const success = toolResults(s2!.conversation).find((r) => r.status === 200)
        expect(success).toBeTruthy()
        expect((success!.body as { breed?: string }).breed).toBe('corgi')
    })
})
