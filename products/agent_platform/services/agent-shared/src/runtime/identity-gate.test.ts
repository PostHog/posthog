import { describe, expect, it, vi } from 'vitest'

import type { IdentityProviderConfig } from '../spec/spec'
import type { Credential } from './credential-broker'
import type { HttpFetcher } from './http-client'
import type { IdentityCredentialStore } from './identity-credential-store'
import { buildIdentityRegistry, createToolIdentity } from './identity-gate'
import type { IdentityLinkStateStore } from './identity-link-state-store'
import type { IdentityProvider } from './identity-provider'
import { MapIdentityProviderRegistry } from './identity-provider'

const OK_CRED: Credential = { kind: 'posthog_bearer', token: 'linked' }

function fakeProvider(over: Partial<IdentityProvider> = {}): IdentityProvider {
    return {
        id: 'posthog',
        credentialTarget: 'posthog_api',
        establishesIdentity: true,
        binding: 'principal',
        allowedHosts: () => ['app.posthog.test'],
        resolve: vi.fn(async () => null),
        initiate: vi.fn(async () => ({ authorizeUrl: 'https://app.posthog.test/oauth/authorize/?x=1', stateId: 's' })),
        complete: vi.fn(),
        ...over,
    }
}

interface Over {
    provider?: IdentityProvider
    agentUserId?: string | null
    unavailableReason?: string
    seed?: { resolve: (t: string) => Promise<Credential | null> }
    log?: (level: 'info' | 'warn' | 'error', msg: string, meta?: Record<string, unknown>) => void
}

function deps(over: Over = {}): { provider: IdentityProvider; toolIdentity: ReturnType<typeof createToolIdentity> } {
    const provider = over.provider ?? fakeProvider()
    const toolIdentity = createToolIdentity({
        registry: new MapIdentityProviderRegistry([provider]),
        agentUserId: over.agentUserId === undefined ? 'au-1' : over.agentUserId,
        teamId: 7,
        applicationId: 'app-1',
        redirectUriFor: (p) => `https://cb.test/link/${p}/callback`,
        unavailableReason: over.unavailableReason,
        seed: over.seed,
        log: over.log,
    })
    return { provider, toolIdentity }
}

describe('buildIdentityRegistry', () => {
    const regDeps = (posthogBaseUrl?: string): Parameters<typeof buildIdentityRegistry>[1] => ({
        links: {} as IdentityLinkStateStore,
        credentials: {} as IdentityCredentialStore,
        http: {} as HttpFetcher,
        secret: () => undefined,
        posthogBaseUrl,
    })
    const posthogCfg: IdentityProviderConfig[] = [
        { kind: 'posthog', id: 'posthog', binding: 'principal', scopes: [], client_id: 'c' },
    ]

    it('builds the posthog provider only when posthogBaseUrl is present (the ingress-callback / runner gap)', () => {
        expect(buildIdentityRegistry(posthogCfg, regDeps('http://localhost:8010')).get('posthog')).not.toBeUndefined()
        // No base → no posthog provider → resolves as "unknown_provider". This is
        // the bug the link callback hit when it didn't thread posthogApiBaseUrl.
        expect(buildIdentityRegistry(posthogCfg, regDeps(undefined)).get('posthog')).toBeUndefined()
    })
})

describe('createToolIdentity.resolve', () => {
    it('returns the trigger-edge seed without touching the store or initiating a link (PostHog Code passthrough)', async () => {
        const provider = fakeProvider()
        const seed = { resolve: vi.fn(async (t: string) => (t === 'posthog_api' ? OK_CRED : null)) }
        const { toolIdentity } = deps({ provider, seed })

        const res = await toolIdentity.resolve('posthog')

        expect(res).toEqual({ kind: 'ok', credential: OK_CRED, allowedHosts: ['app.posthog.test'] })
        expect(seed.resolve).toHaveBeenCalledWith('posthog_api')
        expect(provider.resolve).not.toHaveBeenCalled()
        expect(provider.initiate).not.toHaveBeenCalled()
    })

    it('falls through to the linked store when there is no seed', async () => {
        const provider = fakeProvider({ resolve: vi.fn(async () => OK_CRED) })
        const { toolIdentity } = deps({ provider })
        const res = await toolIdentity.resolve('posthog')
        expect(res).toEqual({ kind: 'ok', credential: OK_CRED, allowedHosts: ['app.posthog.test'] })
    })

    it('returns link_required when unlinked and link-capable', async () => {
        const { toolIdentity } = deps()
        const res = await toolIdentity.resolve('posthog')
        expect(res).toEqual({
            kind: 'link_required',
            provider: 'posthog',
            authorizeUrl: 'https://app.posthog.test/oauth/authorize/?x=1',
        })
    })

    it('fails closed in a shared session WITHOUT consulting the seed (T1 confused-deputy guard)', async () => {
        const provider = fakeProvider()
        const seed = { resolve: vi.fn(async () => OK_CRED) }
        const { toolIdentity } = deps({ provider, seed, unavailableReason: 'shared_session_unsupported' })

        const res = await toolIdentity.resolve('posthog')

        expect(res).toEqual({ kind: 'unavailable', provider: 'posthog', reason: 'shared_session_unsupported' })
        expect(seed.resolve).not.toHaveBeenCalled()
        expect(provider.resolve).not.toHaveBeenCalled()
    })

    it('unknown provider → unavailable', async () => {
        const { toolIdentity } = deps()
        const res = await toolIdentity.resolve('github')
        expect(res).toEqual({ kind: 'unavailable', provider: 'github', reason: 'unknown_provider' })
    })

    it('unlinkable principal (no agentUserId) with no seed → unavailable; with a seed → ok', async () => {
        const noSeed = deps({ agentUserId: null })
        expect(await noSeed.toolIdentity.resolve('posthog')).toEqual({
            kind: 'unavailable',
            provider: 'posthog',
            reason: 'principal_not_linkable',
        })

        const seeded = deps({
            agentUserId: null,
            seed: { resolve: async (t: string) => (t === 'posthog_api' ? OK_CRED : null) },
        })
        expect(await seeded.toolIdentity.resolve('posthog')).toEqual({
            kind: 'ok',
            credential: OK_CRED,
            allowedHosts: ['app.posthog.test'],
        })
    })

    it('degrades a provider throw (unimplemented agent binding) to unavailable', async () => {
        const provider = fakeProvider({
            binding: 'agent',
            resolve: vi.fn(async () => {
                throw new Error('agent_binding_not_implemented')
            }),
        })
        const { toolIdentity } = deps({ provider })
        const res = await toolIdentity.resolve('posthog')
        expect(res).toEqual({ kind: 'unavailable', provider: 'posthog', reason: 'agent_binding_not_implemented' })
    })

    it('logs one identity.resolved line per resolve with the source and no token', async () => {
        const log = vi.fn()
        const seed = { resolve: async (t: string) => (t === 'posthog_api' ? OK_CRED : null) }
        const { toolIdentity } = deps({ seed, log })
        await toolIdentity.resolve('posthog')
        expect(log).toHaveBeenCalledTimes(1)
        const [level, msg, meta] = log.mock.calls[0]
        expect(level).toBe('info')
        expect(msg).toBe('identity.resolved')
        expect(meta).toMatchObject({ provider: 'posthog', source: 'edge_seed' })
        expect(JSON.stringify(meta)).not.toContain('linked')
    })
})

describe('createToolIdentity.relink', () => {
    it('forces a fresh authorize link for an already-linked provider (the reconnect path)', async () => {
        const provider = fakeProvider({ resolve: vi.fn(async () => OK_CRED) })
        const { toolIdentity } = deps({ provider })
        // resolve() would return ok (linked) — relink ignores that and re-initiates.
        const url = await toolIdentity.relink('posthog')
        expect(url).toBe('https://app.posthog.test/oauth/authorize/?x=1')
        expect(provider.initiate).toHaveBeenCalledTimes(1)
        expect(provider.resolve).not.toHaveBeenCalled()
    })

    it('returns null in a shared session and for an unlinkable principal (no relink for someone else)', async () => {
        const shared = deps({ unavailableReason: 'shared_session_unsupported' })
        expect(await shared.toolIdentity.relink('posthog')).toBeNull()

        const unlinkable = deps({ agentUserId: null })
        expect(await unlinkable.toolIdentity.relink('posthog')).toBeNull()
    })

    it('returns null for an unknown provider and when initiate refuses (e.g. seed-only, no OAuth app)', async () => {
        const { toolIdentity } = deps()
        expect(await toolIdentity.relink('github')).toBeNull()

        const seedOnly = fakeProvider({
            initiate: vi.fn(async () => {
                throw new Error('link_unavailable_no_oauth_app')
            }),
        })
        expect(await deps({ provider: seedOnly }).toolIdentity.relink('posthog')).toBeNull()
    })
})
