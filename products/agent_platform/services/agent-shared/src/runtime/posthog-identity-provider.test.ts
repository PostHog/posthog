/**
 * PostHogAuthProvider — the managed identity provider. Verifies the two things
 * that make it more than the generic oauth2 provider:
 *   1. `establishesIdentity` is true.
 *   2. `complete()` reads /oauth/userinfo `sub` and stamps it as the credential
 *      `subject`; the generic provider against the same server stamps nothing.
 *
 * PG-free: in-memory link + credential stores and a scripted HttpFetcher, so it
 * proves the provider logic without the runtime DB.
 */

import { describe, expect, it } from 'vitest'

import type { HttpFetcher } from './http-client'
import type { IdentityCredentialStore, LinkedCredential, PutLinkedCredentialInput } from './identity-credential-store'
import type { CreateLinkStateInput, IdentityLinkStateStore, LinkState } from './identity-link-state-store'
import { Oauth2AuthProvider } from './oauth2-identity-provider'
import { PostHogAuthProvider, SeedOnlyPostHogProvider } from './posthog-identity-provider'

const BASE = 'https://ph.test'

describe('posthog provider credential target', () => {
    it('PostHogAuthProvider resolves under the broker target `posthog_api`', () => {
        const p = new PostHogAuthProvider({
            config: {
                id: 'posthog',
                authorizeUrl: `${BASE}/oauth/authorize/`,
                tokenUrl: `${BASE}/oauth/token/`,
                clientId: 'c',
            },
            links: {} as IdentityLinkStateStore,
            credentials: {} as IdentityCredentialStore,
            http: {} as HttpFetcher,
        })
        expect(p.credentialTarget).toBe('posthog_api')
    })

    it('SeedOnlyPostHogProvider surfaces the seed target + host but cannot link', async () => {
        const p = new SeedOnlyPostHogProvider('posthog', BASE)
        expect(p.credentialTarget).toBe('posthog_api')
        expect(p.allowedHosts()).toEqual(['ph.test'])
        expect(await p.resolve({ agentUserId: 'au', teamId: 1, applicationId: 'a', scopes: [] })).toBeNull()
        await expect(
            p.initiate({ agentUserId: 'au', teamId: 1, applicationId: 'a', scopes: [], redirectUri: 'x' })
        ).rejects.toThrow('link_unavailable_no_oauth_app')
    })
})

// Scripted IdP: token exchange returns a bearer; userinfo returns a fixed sub.
function scriptedHttp(sub: string): HttpFetcher {
    return {
        async fetch(input, init) {
            const url = String(input)
            if (init?.method === 'POST' && url.endsWith('/oauth/token/')) {
                return new Response(
                    JSON.stringify({
                        access_token: 'at-1',
                        refresh_token: 'rt-1',
                        token_type: 'Bearer',
                        expires_in: 3600,
                    }),
                    { status: 200, headers: { 'content-type': 'application/json' } }
                )
            }
            if (url.endsWith('/oauth/userinfo/')) {
                return new Response(JSON.stringify({ sub, email: 'who@posthog.com' }), {
                    status: 200,
                    headers: { 'content-type': 'application/json' },
                })
            }
            return new Response('not found', { status: 404 })
        },
    }
}

class MemLinkStore implements IdentityLinkStateStore {
    private rows = new Map<string, LinkState & { used: boolean }>()
    private seq = 0
    async create(input: CreateLinkStateInput): Promise<string> {
        const id = `state-${++this.seq}`
        this.rows.set(id, {
            id,
            teamId: input.teamId,
            applicationId: input.applicationId,
            agentUserId: input.agentUserId,
            provider: input.provider,
            scopes: input.scopes,
            codeVerifier: input.codeVerifier,
            redirectUri: input.redirectUri,
            used: false,
        })
        return id
    }
    async peek(id: string): Promise<{ applicationId: string; provider: string } | null> {
        const r = this.rows.get(id)
        return r && !r.used ? { applicationId: r.applicationId, provider: r.provider } : null
    }
    async consume(id: string): Promise<LinkState | null> {
        const r = this.rows.get(id)
        if (!r || r.used) {
            return null
        }
        r.used = true
        const { used: _used, ...state } = r
        return state
    }
    async sweepExpired(): Promise<number> {
        return 0
    }
}

class MemCredStore implements IdentityCredentialStore {
    private rows = new Map<string, { input: PutLinkedCredentialInput; subject?: string; state: string }>()
    private key(a: string, p: string): string {
        return `${a}::${p}`
    }
    async put(input: PutLinkedCredentialInput): Promise<void> {
        const k = this.key(input.agentUserId, input.provider)
        const existing = this.rows.get(k)
        // Mirror the SQL COALESCE: a refresh (subject undefined) keeps the prior subject.
        this.rows.set(k, { input, subject: input.subject ?? existing?.subject, state: 'active' })
    }
    async get(agentUserId: string, provider: string): Promise<LinkedCredential | null> {
        const r = this.rows.get(this.key(agentUserId, provider))
        if (!r || r.state !== 'active') {
            return null
        }
        return {
            agentUserId,
            provider,
            credential: r.input.credential,
            scopes: r.input.scopes ?? r.input.credential.scopes ?? [],
        }
    }
    async getEstablishedSubject(agentUserId: string): Promise<string | null> {
        for (const [k, r] of this.rows) {
            if (k.startsWith(`${agentUserId}::`) && r.state === 'active' && r.subject) {
                return r.subject
            }
        }
        return null
    }
    async getAgentScoped(): Promise<LinkedCredential | null> {
        throw new Error('agent_binding_not_implemented')
    }
    async revoke(): Promise<void> {}
    async remove(): Promise<void> {}
}

const initiateArgs = {
    agentUserId: 'au-1',
    teamId: 7,
    applicationId: 'app-1',
    scopes: ['user:read'],
    redirectUri: 'https://cb.test/link/posthog/callback',
}

function posthogProvider(
    http: HttpFetcher,
    deps: { links: MemLinkStore; credentials: MemCredStore }
): PostHogAuthProvider {
    return new PostHogAuthProvider({
        config: {
            id: 'posthog',
            authorizeUrl: `${BASE}/oauth/authorize/`,
            tokenUrl: `${BASE}/oauth/token/`,
            userinfoUrl: `${BASE}/oauth/userinfo/`,
            clientId: 'provisioned-client',
            scopes: ['user:read'],
        },
        links: deps.links,
        credentials: deps.credentials,
        http,
    })
}

describe('PostHogAuthProvider', () => {
    it('establishes identity', () => {
        const provider = posthogProvider(scriptedHttp('phuser-9'), {
            links: new MemLinkStore(),
            credentials: new MemCredStore(),
        })
        expect(provider.establishesIdentity).toBe(true)
    })

    it('stamps the userinfo sub as the credential subject on complete', async () => {
        const links = new MemLinkStore()
        const credentials = new MemCredStore()
        const provider = posthogProvider(scriptedHttp('phuser-9'), { links, credentials })

        const { stateId } = await provider.initiate(initiateArgs)
        await provider.complete({ stateId, query: { code: 'code-1', state: stateId } })

        expect(await credentials.getEstablishedSubject('au-1')).toBe('phuser-9')
        const linked = await credentials.get('au-1', 'posthog')
        expect(linked?.credential.access_token).toBe('at-1')
    })

    it('keeps the established subject across a token refresh (resolve never re-derives it)', async () => {
        const links = new MemLinkStore()
        const credentials = new MemCredStore()
        // expires_in is small so resolve() takes the refresh branch immediately.
        const http: HttpFetcher = {
            async fetch(input, init) {
                const url = String(input)
                if (init?.method === 'POST' && url.endsWith('/oauth/token/')) {
                    return new Response(
                        JSON.stringify({
                            access_token: 'at-2',
                            refresh_token: 'rt-2',
                            token_type: 'Bearer',
                            expires_in: 1,
                        }),
                        { status: 200, headers: { 'content-type': 'application/json' } }
                    )
                }
                if (url.endsWith('/oauth/userinfo/')) {
                    return new Response(JSON.stringify({ sub: 'phuser-9' }), {
                        status: 200,
                        headers: { 'content-type': 'application/json' },
                    })
                }
                return new Response('nope', { status: 404 })
            },
        }
        const provider = new PostHogAuthProvider({
            config: {
                id: 'posthog',
                authorizeUrl: `${BASE}/oauth/authorize/`,
                tokenUrl: `${BASE}/oauth/token/`,
                userinfoUrl: `${BASE}/oauth/userinfo/`,
                clientId: 'provisioned-client',
                scopes: ['user:read'],
            },
            links,
            credentials,
            http,
            now: () => 10_000_000, // far past the 1s token expiry → forces a refresh
        })

        const { stateId } = await provider.initiate(initiateArgs)
        await provider.complete({ stateId, query: { code: 'code-1', state: stateId } })
        // Refresh path runs (token already expired against the fixed clock).
        await provider.resolve({ agentUserId: 'au-1', teamId: 7, applicationId: 'app-1', scopes: ['user:read'] })

        expect(await credentials.getEstablishedSubject('au-1')).toBe('phuser-9')
    })

    it('the generic oauth2 provider stamps no subject against the same server', async () => {
        const links = new MemLinkStore()
        const credentials = new MemCredStore()
        const provider = new Oauth2AuthProvider({
            config: {
                id: 'byo',
                authorizeUrl: `${BASE}/oauth/authorize/`,
                tokenUrl: `${BASE}/oauth/token/`,
                userinfoUrl: `${BASE}/oauth/userinfo/`,
                clientId: 'byo-client',
                scopes: ['user:read'],
            },
            links,
            credentials,
            http: scriptedHttp('phuser-9'),
        })
        expect(provider.establishesIdentity).toBe(false)

        const { stateId } = await provider.initiate(initiateArgs)
        await provider.complete({ stateId, query: { code: 'code-1', state: stateId } })

        // Linked as a capability, but no subject → not identity-bearing.
        expect(await credentials.getEstablishedSubject('au-1')).toBeNull()
        expect(await credentials.get('au-1', 'byo')).not.toBeNull()
    })
})
