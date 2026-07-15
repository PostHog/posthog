/**
 * Admission engine — the architecture-level e2e, PG-free. Drives the full arc
 * with the REAL `Oauth2AuthProvider` against scripted IdPs and in-memory stores:
 *
 *   claim → auth_required → OAuth round-trip → binding + canonical identity →
 *   re-admit (durable) → second transport binds to the SAME identity →
 *   secondary provider links to the SAME canonical identity → per-request bearer
 *   admits inline → passthrough when no authoritative provider → fail-closed.
 */

import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import type { AgentUser, IdentityStore } from '../persistence/identity-store'
import { AgentSpecSchema } from '../spec/spec'
import type { AgentApplication, AgentRevision, AgentSpec } from '../spec/spec'
import { AdmissionService, canonicalKind } from './admission'
import type { HttpFetcher } from './http-client'
import type { IdentityCredentialStore, LinkedCredential, PutLinkedCredentialInput } from './identity-credential-store'
import type { CreateLinkStateInput, IdentityLinkStateStore, LinkState } from './identity-link-state-store'
import type { BearerVerification, IdentityProvider } from './identity-provider'
import { MapIdentityProviderRegistry } from './identity-provider'
import { Oauth2AuthProvider } from './oauth2-identity-provider'
import type { TransportClaim } from './transport'
import { MemoryTransportBindingStore } from './transport-binding-store'

// ---------- in-memory stores ----------

let auSeq = 0
class MemIdentityStore implements IdentityStore {
    readonly rows = new Map<string, AgentUser>()
    private key(app: string, kind: string, id: string): string {
        return `${app}::${kind}::${id}`
    }
    async findOrCreate(input: {
        team_id: number
        application_id: string
        principal_kind: string
        principal_id: string
        metadata?: Record<string, unknown>
    }): Promise<AgentUser> {
        const k = this.key(input.application_id, input.principal_kind, input.principal_id)
        const existing = this.rows.get(k)
        if (existing) {
            return existing
        }
        const row: AgentUser = {
            id: `au-${++auSeq}`,
            team_id: input.team_id,
            application_id: input.application_id,
            principal_kind: input.principal_kind,
            principal_id: input.principal_id,
            metadata: input.metadata,
            created_at: '2026-01-01T00:00:00Z',
        }
        this.rows.set(k, row)
        return row
    }
    async find(input: {
        application_id: string
        principal_kind: string
        principal_id: string
    }): Promise<AgentUser | null> {
        return this.rows.get(this.key(input.application_id, input.principal_kind, input.principal_id)) ?? null
    }
    async getById(agentUserId: string): Promise<AgentUser | null> {
        for (const r of this.rows.values()) {
            if (r.id === agentUserId) {
                return r
            }
        }
        return null
    }
}

class MemLinkStore implements IdentityLinkStateStore {
    private rows = new Map<string, LinkState & { used: boolean }>()
    private seq = 0
    async create(input: CreateLinkStateInput): Promise<string> {
        const id = `state-${++this.seq}`
        this.rows.set(id, { id, ...input, used: false } as LinkState & { used: boolean })
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
        const { used: _u, ...state } = r
        return state
    }
    async sweepExpired(): Promise<number> {
        return 0
    }
}

class MemCredStore implements IdentityCredentialStore {
    readonly rows = new Map<string, { input: PutLinkedCredentialInput; subject?: string; state: string }>()
    private key(a: string, p: string): string {
        return `${a}::${p}`
    }
    async put(input: PutLinkedCredentialInput): Promise<void> {
        const k = this.key(input.agentUserId, input.provider)
        const existing = this.rows.get(k)
        this.rows.set(k, { input, subject: input.subject ?? existing?.subject, state: 'active' })
    }
    async get(agentUserId: string, provider: string): Promise<LinkedCredential | null> {
        const r = this.rows.get(this.key(agentUserId, provider))
        if (!r || r.state !== 'active') {
            return null
        }
        return { agentUserId, provider, credential: r.input.credential, scopes: r.input.scopes ?? [] }
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
    async revoke(agentUserId: string, provider: string): Promise<void> {
        const r = this.rows.get(this.key(agentUserId, provider))
        if (r) {
            r.state = 'revoked'
        }
    }
    async remove(agentUserId: string, provider: string): Promise<void> {
        this.rows.delete(this.key(agentUserId, provider))
    }
}

// ---------- scripted IdP ----------

interface FakeIdp {
    base: string
    authorizeUrl: string
    tokenUrl: string
    userinfoUrl: string
    sub: string
    issued: string[]
}

function makeIdp(base: string, sub: string): FakeIdp {
    return {
        base,
        authorizeUrl: `${base}/authorize`,
        tokenUrl: `${base}/token`,
        userinfoUrl: `${base}/userinfo`,
        sub,
        issued: [],
    }
}

/** One HttpFetcher routing /token + /userinfo across several IdPs by host. */
function combinedHttp(idps: FakeIdp[]): HttpFetcher {
    const byHost = new Map(idps.map((i) => [new URL(i.base).host, i]))
    return {
        async fetch(input, init) {
            const url = new URL(String(input))
            const idp = byHost.get(url.host)
            if (!idp) {
                return new Response('no idp', { status: 404 })
            }
            if (init?.method === 'POST' && url.pathname === '/token') {
                const token = `${idp.sub}-at-${idp.issued.length + 1}`
                idp.issued.push(token)
                return new Response(
                    JSON.stringify({
                        access_token: token,
                        refresh_token: `${idp.sub}-rt`,
                        token_type: 'Bearer',
                        expires_in: 3600,
                    }),
                    { status: 200, headers: { 'content-type': 'application/json' } }
                )
            }
            if (url.pathname === '/userinfo') {
                return new Response(JSON.stringify({ sub: idp.sub, email: `${idp.sub}@example.com` }), {
                    status: 200,
                    headers: { 'content-type': 'application/json' },
                })
            }
            return new Response('not found', { status: 404 })
        },
    }
}

// ---------- fixtures + harness ----------

const APP: AgentApplication = {
    id: 'app-1',
    team_id: 7,
    slug: 'bot',
    name: 'Bot',
    description: '',
    live_revision_id: 'rev-1',
    archived: false,
}

function revWith(authoritative?: string): AgentRevision {
    return {
        id: 'rev-1',
        application_id: 'app-1',
        parent_revision_id: null,
        created_by_id: null,
        created_at: '2026-01-01T00:00:00Z',
        state: 'live',
        bundle_uri: 's3://x',
        bundle_sha256: null,
        spec: { authoritative_provider: authoritative } as AgentSpec,
        encrypted_env: null,
    }
}

const REDIRECT = (p: string): string => `https://cb.test/link/${p}/callback`

interface Harness {
    admission: AdmissionService
    identities: MemIdentityStore
    bindings: MemoryTransportBindingStore
    credentials: MemCredStore
    links: MemLinkStore
    registry: MapIdentityProviderRegistry
}

function harness(idps: FakeIdp[]): Harness {
    const identities = new MemIdentityStore()
    const bindings = new MemoryTransportBindingStore()
    const credentials = new MemCredStore()
    const links = new MemLinkStore()
    const http = combinedHttp(idps)
    const registry = new MapIdentityProviderRegistry(
        idps.map(
            (i) =>
                new Oauth2AuthProvider({
                    config: {
                        id: providerIdFor(i),
                        authorizeUrl: i.authorizeUrl,
                        tokenUrl: i.tokenUrl,
                        userinfoUrl: i.userinfoUrl,
                        clientId: `${providerIdFor(i)}-client`,
                        scopes: ['read'],
                    },
                    links,
                    credentials,
                    http,
                })
        )
    )
    const admission = new AdmissionService({ registry, identities, bindings, credentials, redirectUriFor: REDIRECT })
    return { admission, identities, bindings, credentials, links, registry }
}

const providerIdFor = (i: FakeIdp): string => new URL(i.base).host.split('.')[0]

/** Simulate the browser leg: pull `state` out of the authorize URL, hand a code
 *  back through the admission callback. */
async function driveLink(h: Harness, authorizeUrl: string): Promise<ReturnType<AdmissionService['complete']>> {
    const u = new URL(authorizeUrl)
    const state = u.searchParams.get('state')
    const providerId = h.registry.all().find((p) => p.id && authorizeUrl.includes(p.id))?.id
    expect(state).toBeTruthy()
    expect(providerId).toBeTruthy()
    return h.admission.complete(providerId!, state!, { code: 'code-1', state: state! })
}

describe('AdmissionService', () => {
    it('Slack: unbound → auth_required → link writes binding + canonical → re-admit is durable', async () => {
        const work = makeIdp('https://work.example', 'alice')
        const h = harness([work])
        const claim: TransportClaim = { transport: 'slack', subjectId: 'T01:U01' }

        const first = await h.admission.resolve(claim, { application: APP, revision: revWith('work') })
        expect(first.kind).toBe('auth_required')
        if (first.kind !== 'auth_required') {
            return
        }
        expect(first.provider).toBe('work')
        expect(first.authorizeUrl).toContain('work.example/authorize')

        const verified = await driveLink(h, first.authorizeUrl)
        expect(verified.subject).toBe('alice')
        expect(verified.provider).toBe('work')

        // Canonical identity is an AgentUser keyed on the authoritative subject.
        const canonical = await h.identities.find({
            application_id: 'app-1',
            principal_kind: canonicalKind('work'),
            principal_id: 'alice',
        })
        expect(canonical?.id).toBe(verified.canonicalId)

        // Authoritative credential persisted under the canonical id, resolvable.
        const cred = await h.credentials.get(verified.canonicalId, 'work')
        expect(cred?.credential.access_token).toBe('alice-at-1')

        // Second turn: durable binding admits without a link.
        const second = await h.admission.resolve(claim, { application: APP, revision: revWith('work') })
        expect(second.kind).toBe('admitted')
        if (second.kind === 'admitted') {
            expect(second.identity.canonicalId).toBe(verified.canonicalId)
            expect(second.identity.transportAgentUserId).toBe(verified.transportAgentUserId)
        }
    })

    it('one identity, many transports: Slack + Discord for the same person bind to ONE canonical identity', async () => {
        const work = makeIdp('https://work.example', 'alice')
        const h = harness([work])
        const rev = revWith('work')

        const slack = await h.admission.resolve(
            { transport: 'slack', subjectId: 'T:US' },
            { application: APP, revision: rev }
        )
        const slackId = slack.kind === 'auth_required' ? (await driveLink(h, slack.authorizeUrl)).canonicalId : ''

        const discord = await h.admission.resolve(
            { transport: 'discord', subjectId: 'G:UD' },
            { application: APP, revision: rev }
        )
        expect(discord.kind).toBe('auth_required')
        const discordId = discord.kind === 'auth_required' ? (await driveLink(h, discord.authorizeUrl)).canonicalId : ''

        expect(slackId).toBe(discordId) // same subject → same canonical identity
        const all = await h.bindings.listForCanonical('app-1', slackId)
        expect(all.map((b) => b.transportAgentUserId).sort()).toHaveLength(2)
        expect(new Set(all.map((b) => b.transportAgentUserId)).size).toBe(2) // two distinct transports
    })

    it('multi-provider: a secondary provider links to the SAME canonical identity, shared across transports', async () => {
        const work = makeIdp('https://work.example', 'alice') // authoritative
        const dogs = makeIdp('https://dogs.example', 'alice-dog') // secondary capability
        const h = harness([work, dogs])
        const rev = revWith('work')

        // Admit via Slack.
        const admit = await h.admission.resolve(
            { transport: 'slack', subjectId: 'T:US' },
            { application: APP, revision: rev }
        )
        const canonicalId = admit.kind === 'auth_required' ? (await driveLink(h, admit.authorizeUrl)).canonicalId : ''
        expect(canonicalId).toBeTruthy()

        // Link the secondary 'dogs' provider directly against the CANONICAL id.
        const dogsProvider = h.registry.require('dogs')
        const { authorizeUrl } = await dogsProvider.initiate({
            agentUserId: canonicalId,
            teamId: 7,
            applicationId: 'app-1',
            scopes: [],
            redirectUri: REDIRECT('dogs'),
        })
        const dogsState = new URL(authorizeUrl).searchParams.get('state')!
        await dogsProvider.complete({ stateId: dogsState, query: { code: 'c', state: dogsState } })

        // Resolvable as the canonical identity → usable from ANY of that person's
        // transports, because every transport binds to this one canonical id.
        const dogCred = await dogsProvider.resolve({
            agentUserId: canonicalId,
            teamId: 7,
            applicationId: 'app-1',
            scopes: [],
        })
        expect(dogCred?.kind).toBe('oauth_bearer')
        expect(dogCred && 'token' in dogCred ? dogCred.token : '').toBe('alice-dog-at-1')
    })

    it('HTTP: a per-request bearer the provider can verify inline admits without a link', async () => {
        const identities = new MemIdentityStore()
        const bindings = new MemoryTransportBindingStore()
        const credentials = new MemCredStore()
        // An authoritative provider that proves identity from a bearer (no OAuth leg).
        const provider: IdentityProvider = {
            id: 'work',
            credentialTarget: 'work',
            establishesIdentity: true,
            binding: 'principal',
            allowedHosts: () => ['work.example'],
            initiate: async () => {
                throw new Error('should_not_initiate')
            },
            exchange: async () => {
                throw new Error('should_not_exchange')
            },
            complete: async () => {
                throw new Error('should_not_complete')
            },
            resolve: async () => null,
            async verifyBearer(token: string): Promise<BearerVerification | null> {
                return token === 'good-bearer'
                    ? { subject: 'alice', stored: { access_token: token }, scopes: ['read'] }
                    : null
            },
        }
        const admission = new AdmissionService({
            registry: new MapIdentityProviderRegistry([provider]),
            identities,
            bindings,
            credentials,
            redirectUriFor: REDIRECT,
        })
        const res = await admission.resolve(
            { transport: 'http', subjectId: 'jwt-sub', bearer: { token: 'good-bearer' } },
            { application: APP, revision: revWith('work') }
        )
        expect(res.kind).toBe('admitted')
        if (res.kind === 'admitted') {
            expect(res.identity.subject).toBe('alice')
            const cred = await credentials.get(res.identity.canonicalId, 'work')
            expect(cred?.credential.access_token).toBe('good-bearer')
            const binding = await bindings.find('app-1', res.identity.transportAgentUserId)
            expect(binding?.canonicalAgentUserId).toBe(res.identity.canonicalId)
        }
    })

    it('HTTP: a revoked bearer is NOT rescued by the binding a prior valid bearer wrote', async () => {
        // The per-request contract: a bearer is re-verified every request, even
        // after one has already established a binding. A token that later turns
        // invalid (revoked/expired) must stop admitting — the durable binding
        // must not substitute for the freshness check.
        const identities = new MemIdentityStore()
        const bindings = new MemoryTransportBindingStore()
        const credentials = new MemCredStore()
        const provider: IdentityProvider = {
            id: 'work',
            credentialTarget: 'work',
            establishesIdentity: true,
            binding: 'principal',
            allowedHosts: () => ['work.example'],
            // A real OAuth leg so a failed bearer re-auths (auth_required) rather
            // than erroring — makes the "not admitted" assertion crisp.
            initiate: async () => ({ authorizeUrl: 'https://work.example/authorize?state=s', stateId: 's' }),
            exchange: async () => {
                throw new Error('should_not_exchange')
            },
            complete: async () => {
                throw new Error('should_not_complete')
            },
            resolve: async () => null,
            async verifyBearer(token: string): Promise<BearerVerification | null> {
                return token === 'good-bearer'
                    ? { subject: 'alice', stored: { access_token: token }, scopes: ['read'] }
                    : null
            },
        }
        const admission = new AdmissionService({
            registry: new MapIdentityProviderRegistry([provider]),
            identities,
            bindings,
            credentials,
            redirectUriFor: REDIRECT,
        })
        const claim = (token: string): TransportClaim => ({
            transport: 'http',
            subjectId: 'jwt-sub',
            bearer: { token },
        })
        const ctx = { application: APP, revision: revWith('work') }

        // First request with a valid bearer → admitted + binding written.
        const ok = await admission.resolve(claim('good-bearer'), ctx)
        expect(ok.kind).toBe('admitted')
        const transportUserId = ok.kind === 'admitted' ? ok.identity.transportAgentUserId : ''
        expect((await bindings.find('app-1', transportUserId))?.canonicalAgentUserId).toBeTruthy()

        // Same transport principal, now a revoked/expired bearer → must re-auth,
        // NOT admit via the stale binding.
        const revoked = await admission.resolve(claim('revoked-bearer'), ctx)
        expect(revoked.kind).toBe('auth_required')
    })

    it('passthrough: no authoritative provider → transport claim is the identity', async () => {
        const h = harness([])
        const res = await h.admission.resolve(
            { transport: 'slack', subjectId: 'T:U' },
            { application: APP, revision: revWith(undefined) }
        )
        expect(res.kind).toBe('passthrough')
        if (res.kind === 'passthrough') {
            const u = await h.identities.getById(res.transportAgentUserId)
            expect(u?.principal_kind).toBe('slack')
        }
    })

    it('fails closed on an unknown authoritative provider', async () => {
        const work = makeIdp('https://work.example', 'alice')
        const h = harness([work])
        const res = await h.admission.resolve(
            { transport: 'slack', subjectId: 'T:U' },
            { application: APP, revision: revWith('nope') }
        )
        expect(res.kind).toBe('error')
    })

    it('replay: completing the same link state twice fails (single-use)', async () => {
        const work = makeIdp('https://work.example', 'alice')
        const h = harness([work])
        const first = await h.admission.resolve(
            { transport: 'slack', subjectId: 'T:U' },
            { application: APP, revision: revWith('work') }
        )
        if (first.kind !== 'auth_required') {
            throw new Error('expected auth_required')
        }
        const state = new URL(first.authorizeUrl).searchParams.get('state')!
        await h.admission.complete('work', state, { code: 'c', state })
        await expect(h.admission.complete('work', state, { code: 'c', state })).rejects.toThrow('oauth_invalid_state')
    })

    it('dangling binding (canonical vanished) falls through to auth_required', async () => {
        const work = makeIdp('https://work.example', 'alice')
        const h = harness([work])
        const rev = revWith('work')
        const claim: TransportClaim = { transport: 'slack', subjectId: 'T:U' }
        const first = await h.admission.resolve(claim, { application: APP, revision: rev })
        const verified = first.kind === 'auth_required' ? await driveLink(h, first.authorizeUrl) : null
        expect(verified).toBeTruthy()
        // Drop the canonical identity row out from under the binding.
        h.identities.rows.delete(`app-1::${canonicalKind('work')}::alice`)
        const again = await h.admission.resolve(claim, { application: APP, revision: rev })
        expect(again.kind).toBe('auth_required') // not a crash, not a stale admit
    })

    it('stale binding: authoritative provider swapped since link → re-auth against the new provider', async () => {
        // A binding is scoped to the provider that established it. If the agent
        // switches its authoritative_provider, the prior binding must NOT admit
        // the transport principal against the new provider — otherwise a
        // once-linked Slack user stays "authenticated" as a different identity
        // system than the current spec demands.
        const work = makeIdp('https://work.example', 'alice')
        const dogs = makeIdp('https://dogs.example', 'rex')
        const h = harness([work, dogs])
        const claim: TransportClaim = { transport: 'slack', subjectId: 'T:U' }

        // Link under provider 'work'.
        const first = await h.admission.resolve(claim, { application: APP, revision: revWith('work') })
        expect(first.kind).toBe('auth_required')
        if (first.kind === 'auth_required') {
            await driveLink(h, first.authorizeUrl)
        }
        // Sanity: same claim + same authoritative provider → durable admit.
        const durable = await h.admission.resolve(claim, { application: APP, revision: revWith('work') })
        expect(durable.kind).toBe('admitted')

        // Agent flips authoritative_provider to 'dogs'. The old binding must
        // not carry over — force a fresh link against 'dogs'.
        const flipped = await h.admission.resolve(claim, { application: APP, revision: revWith('dogs') })
        expect(flipped.kind).toBe('auth_required')
        if (flipped.kind === 'auth_required') {
            expect(flipped.provider).toBe('dogs')
        }
    })

    it('revoked authoritative credential invalidates the binding → re-auth', async () => {
        // A binding without a live credential is meaningless — the authoritative
        // provider has nothing to prove the identity with anymore. Revoking
        // (or removing) the credential must stop admitting via the durable
        // binding until the user re-links.
        const work = makeIdp('https://work.example', 'alice')
        const h = harness([work])
        const rev = revWith('work')
        const claim: TransportClaim = { transport: 'slack', subjectId: 'T:U' }

        const first = await h.admission.resolve(claim, { application: APP, revision: rev })
        const linked = first.kind === 'auth_required' ? await driveLink(h, first.authorizeUrl) : null
        expect(linked).toBeTruthy()

        // Sanity: durable admit works while the credential is active.
        const admittedAgain = await h.admission.resolve(claim, { application: APP, revision: rev })
        expect(admittedAgain.kind).toBe('admitted')

        // Credential revoked (e.g. admin unlinked). Binding still exists but
        // must no longer admit — a fresh link is required.
        await h.credentials.revoke(linked!.canonicalId, 'work')
        const afterRevoke = await h.admission.resolve(claim, { application: APP, revision: rev })
        expect(afterRevoke.kind).toBe('auth_required')
    })

    it('re-auth as a different subject replaces the binding (account switch)', async () => {
        const work = makeIdp('https://work.example', 'alice')
        const h = harness([work])
        const rev = revWith('work')
        const claim: TransportClaim = { transport: 'slack', subjectId: 'T:U' }
        const a = await h.admission.resolve(claim, { application: APP, revision: rev })
        const first = a.kind === 'auth_required' ? await driveLink(h, a.authorizeUrl) : null

        // The IdP now proves a different subject for the same transport principal.
        work.sub = 'bob'
        const b = await h.admission.resolve(claim, { application: APP, revision: rev })
        // Still admitted via the OLD binding until re-link; force a re-link instead.
        const transportUserId = first!.transportAgentUserId
        await h.bindings.unbind('app-1', transportUserId)
        const c = await h.admission.resolve(claim, { application: APP, revision: rev })
        const second = c.kind === 'auth_required' ? await driveLink(h, c.authorizeUrl) : null
        expect(second!.subject).toBe('bob')
        expect(second!.canonicalId).not.toBe(first!.canonicalId)
        // Exactly one binding for this transport principal — the new one.
        const binding = await h.bindings.find('app-1', transportUserId)
        expect(binding?.canonicalAgentUserId).toBe(second!.canonicalId)
        void b
    })

    it('complete() rejects a provider that does not match the link state', async () => {
        const work = makeIdp('https://work.example', 'alice')
        const dogs = makeIdp('https://dogs.example', 'rex')
        const h = harness([work, dogs])
        const a = await h.admission.resolve(
            { transport: 'slack', subjectId: 'T:U' },
            { application: APP, revision: revWith('work') }
        )
        if (a.kind !== 'auth_required') {
            throw new Error('expected auth_required')
        }
        const state = new URL(a.authorizeUrl).searchParams.get('state')!
        // The link state is for 'work'; completing as 'dogs' must fail.
        await expect(h.admission.complete('dogs', state, { code: 'c', state })).rejects.toThrow('oauth_invalid_state')
    })
})

describe('AgentSpecSchema.authoritative_provider validation', () => {
    const base = { models: { mode: 'auto', level: 'medium', optimize_for: 'cost' } }
    const dogs = (userinfo?: string): Record<string, unknown> => ({
        kind: 'oauth2',
        id: 'dogs',
        authorize_url: 'https://d/authorize',
        token_url: 'https://d/token',
        client_id: 'c',
        ...(userinfo ? { userinfo_url: userinfo } : {}),
    })

    it('rejects an authoritative_provider with no matching identity_providers entry', () => {
        const r = AgentSpecSchema.safeParse({ ...base, authoritative_provider: 'nope' })
        expect(r.success).toBe(false)
    })

    it('rejects an oauth2 authoritative provider without userinfo_url (cannot prove a subject)', () => {
        const r = AgentSpecSchema.safeParse({
            ...base,
            authoritative_provider: 'dogs',
            identity_providers: [dogs()],
        })
        expect(r.success).toBe(false)
    })

    it('accepts an oauth2 authoritative provider with userinfo_url', () => {
        const r = AgentSpecSchema.safeParse({
            ...base,
            authoritative_provider: 'dogs',
            identity_providers: [dogs('https://d/userinfo')],
        })
        expect(r.success).toBe(true)
    })

    it('accepts a posthog authoritative provider', () => {
        const r = AgentSpecSchema.safeParse({
            ...base,
            authoritative_provider: 'posthog',
            identity_providers: [{ kind: 'posthog', id: 'posthog' }],
        })
        expect(r.success).toBe(true)
    })

    it('accepts a spec with no authoritative_provider (passthrough)', () => {
        expect(AgentSpecSchema.safeParse(base).success).toBe(true)
    })

    it('rejects authoritative_provider combined with a trigger whose ingress does not yet call admission', () => {
        // Fail-closed: today only the slack trigger runs `buildAdmission()`
        // before enqueue. A spec that mixes an authoritative provider with a
        // webhook / chat / mcp trigger would silently bypass admission on that
        // path. Loosen this once the other triggers wire the gate.
        const r = AgentSpecSchema.safeParse({
            ...base,
            authoritative_provider: 'posthog',
            identity_providers: [{ kind: 'posthog', id: 'posthog' }],
            triggers: [
                {
                    type: 'webhook',
                    config: { path: '/hook' },
                    auth: { modes: [{ type: 'shared_secret', header: 'x-key', secret_ref: 'S' }] },
                },
            ],
        })
        expect(r.success).toBe(false)
        if (!r.success) {
            const msg = r.error.issues.map((i) => i.message).join('\n')
            expect(msg).toMatch(/webhook/)
        }
    })

    it('accepts authoritative_provider combined with a slack trigger (admission-wired)', () => {
        const r = AgentSpecSchema.safeParse({
            ...base,
            authoritative_provider: 'posthog',
            identity_providers: [{ kind: 'posthog', id: 'posthog' }],
            triggers: [{ type: 'slack', config: { trusted_workspaces: ['T01'] } }],
        })
        expect(r.success).toBe(true)
    })

    it('still serializes to JSON Schema (the refine does not break toJSONSchema)', () => {
        expect(() => z.toJSONSchema(AgentSpecSchema, { reused: 'ref' })).not.toThrow()
    })
})
