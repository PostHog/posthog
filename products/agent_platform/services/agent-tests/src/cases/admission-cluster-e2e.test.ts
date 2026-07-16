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
 */

import request from 'supertest'
import { afterEach, beforeAll, describe, expect, it } from 'vitest'

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

    // Drive the real OAuth callback on the ingress route: browser hits the IdP
    // /authorize (302 → our callback), then GET /link/dogs/callback?state&code.
    const completeLink = async (authorizeUrl: string): Promise<void> => {
        const res = await fetch(authorizeUrl, { redirect: 'manual' })
        const loc = new URL(res.headers.get('location') ?? '')
        await request(c.ingress)
            .get(loc.pathname)
            .query({ state: loc.searchParams.get('state') ?? '', code: loc.searchParams.get('code') ?? '' })
            .expect(200)
    }

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
        await completeLink(authorizeUrl)
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
