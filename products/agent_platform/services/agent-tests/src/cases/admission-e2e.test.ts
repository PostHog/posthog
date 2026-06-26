/**
 * Admission e2e — the authoritative-provider model end to end against REAL
 * Postgres + the REAL `dogs` OAuth server. Proves the rebuilt identity arc with
 * actual durable bindings, canonical identities, and credentials in the DB:
 *
 *   Slack claim → auth_required → real /authorize → complete → binding + canonical
 *   identity + authoritative credential persisted → re-resolve is admitted
 *   (durable) → a Discord claim for the SAME person binds to the SAME canonical
 *   identity → the authoritative credential actually calls the protected API.
 *
 * No Express/queue: this exercises the AdmissionService + PG stores + a real IdP,
 * which is the architecture the ingress edge will call. Wiring the ingress routes
 * onto this is the next step.
 */

import { randomUUID } from 'node:crypto'
import { Pool } from 'pg'
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import {
    AdmissionService,
    canonicalKind,
    HttpClient,
    MapIdentityProviderRegistry,
    Oauth2AuthProvider,
    PgIdentityCredentialStore,
    PgIdentityLinkStateStore,
    PgIdentityStore,
    PgTransportBindingStore,
} from '@posthog/agent-shared'
import type { AgentApplication, AgentRevision, AgentSpec, TransportClaim } from '@posthog/agent-shared'
import { isReachable, reset } from '@posthog/agent-shared/testing'

import { DogServer, startDogServer } from '../harness/dog-oauth-server'

const TEST_DB_URL =
    process.env.AGENT_TEST_DB_URL ?? 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue_test'
const KEY = '01234567890123456789012345678901'
const REDIRECT = (p: string): string => `http://callback.test/link/${p}/callback`

const maybeDescribe = process.env.SKIP_PG_TESTS === '1' ? describe.skip : describe

maybeDescribe('Admission e2e (authoritative provider × dogs IdP × real PG)', () => {
    let pool: Pool
    let reachable = false
    let dog: DogServer

    beforeAll(async () => {
        reachable = await isReachable(TEST_DB_URL)
        if (reachable) {
            pool = new Pool({ connectionString: TEST_DB_URL, max: 4 })
        }
    })

    beforeEach(async () => {
        if (reachable) {
            await reset({ databaseUrl: TEST_DB_URL })
        }
    })

    afterAll(async () => {
        await pool?.end().catch(() => undefined)
    })

    // ---- harness wiring: real PG stores + real Oauth2 provider for `dogs` ----

    function build(): {
        admission: AdmissionService
        identities: PgIdentityStore
        bindings: PgTransportBindingStore
        credentials: PgIdentityCredentialStore
        provider: Oauth2AuthProvider
    } {
        const links = new PgIdentityLinkStateStore(pool)
        const credentials = new PgIdentityCredentialStore(pool, { encryptionSaltKeys: KEY })
        const identities = new PgIdentityStore(pool)
        const bindings = new PgTransportBindingStore(pool)
        const provider = new Oauth2AuthProvider({
            config: {
                id: 'dogs',
                authorizeUrl: dog.authorizeUrl,
                tokenUrl: dog.tokenUrl,
                userinfoUrl: dog.userinfoUrl, // lets the provider derive a subject
                clientId: 'dogs-client',
                scopes: ['read:dog'],
            },
            links,
            credentials,
            http: new HttpClient({}),
        })
        const admission = new AdmissionService({
            registry: new MapIdentityProviderRegistry([provider]),
            identities,
            bindings,
            credentials,
            redirectUriFor: REDIRECT,
        })
        return { admission, identities, bindings, credentials, provider }
    }

    const APP = (): AgentApplication => ({
        id: randomUUID(),
        team_id: 1,
        slug: 'bot',
        name: 'Bot',
        description: '',
        live_revision_id: null,
        archived: false,
    })

    const revFor = (app: AgentApplication, authoritative?: string): AgentRevision => ({
        id: randomUUID(),
        application_id: app.id,
        parent_revision_id: null,
        created_by_id: null,
        created_at: '2026-01-01T00:00:00Z',
        state: 'live',
        bundle_uri: 's3://x',
        bundle_sha256: null,
        spec: { authoritative_provider: authoritative } as AgentSpec,
        encrypted_env: null,
    })

    // Simulate the browser leg: visit /authorize, capture ?code&state.
    async function visitAuthorize(authorizeUrl: string): Promise<{ code: string; state: string }> {
        const res = await fetch(authorizeUrl, { redirect: 'manual' })
        expect(res.status).toBe(302)
        const loc = new URL(res.headers.get('location') ?? '')
        return { code: loc.searchParams.get('code') ?? '', state: loc.searchParams.get('state') ?? '' }
    }

    it('full arc: Slack unbound → link → durable admit; Discord binds to the SAME identity; cred calls the API', async () => {
        if (!reachable) {
            return
        }
        dog = await startDogServer({ userSub: 'employee-7' })
        try {
            const { admission, identities, bindings, credentials, provider } = build()
            const app = APP()
            const rev = revFor(app, 'dogs')
            const slack: TransportClaim = { transport: 'slack', subjectId: 'T01:U01' }

            // 1. First contact: not authenticated → auth_required.
            const first = await admission.resolve(slack, { application: app, revision: rev })
            expect(first.kind).toBe('auth_required')
            if (first.kind !== 'auth_required') {
                return
            }
            expect(first.provider).toBe('dogs')
            expect(first.authorizeUrl).toContain(dog.baseUrl)

            // 2. Browser authenticates; callback completes the link.
            const { code, state } = await visitAuthorize(first.authorizeUrl)
            const verified = await admission.complete('dogs', state, { code })
            expect(verified.subject).toBe('employee-7')

            // 3. Persistence: canonical identity, binding, authoritative credential.
            const canonical = await identities.find({
                application_id: app.id,
                principal_kind: canonicalKind('dogs'),
                principal_id: 'employee-7',
            })
            expect(canonical?.id).toBe(verified.canonicalId)
            const binding = await bindings.find(app.id, verified.transportAgentUserId)
            expect(binding?.canonicalAgentUserId).toBe(verified.canonicalId)
            const stored = await credentials.get(verified.canonicalId, 'dogs')
            expect(stored).not.toBeNull()

            // 4. Next turn: durable binding admits with no link.
            const second = await admission.resolve(slack, { application: app, revision: rev })
            expect(second.kind).toBe('admitted')
            if (second.kind === 'admitted') {
                expect(second.identity.canonicalId).toBe(verified.canonicalId)
            }

            // 5. Same person via Discord → auth_required, then SAME canonical identity.
            const discord: TransportClaim = { transport: 'discord', subjectId: 'G:UD' }
            const dFirst = await admission.resolve(discord, { application: app, revision: rev })
            expect(dFirst.kind).toBe('auth_required')
            if (dFirst.kind !== 'auth_required') {
                return
            }
            const dAuth = await visitAuthorize(dFirst.authorizeUrl)
            const dVerified = await admission.complete('dogs', dAuth.state, { code: dAuth.code })
            expect(dVerified.canonicalId).toBe(verified.canonicalId) // one identity, two transports
            expect(dVerified.transportAgentUserId).not.toBe(verified.transportAgentUserId)

            const allBindings = await bindings.listForCanonical(app.id, verified.canonicalId)
            expect(allBindings).toHaveLength(2)

            // 6. The payoff: the authoritative credential actually works against the API.
            const cred = await provider.resolve({
                agentUserId: verified.canonicalId,
                teamId: 1,
                applicationId: app.id,
                scopes: [],
            })
            const token = cred?.kind === 'oauth_bearer' ? cred.token : ''
            const api = await fetch(dog.apiUrl, { headers: { Authorization: `Bearer ${token}` } })
            expect(api.status).toBe(200)
            expect((await api.json()) as { breed: string }).toMatchObject({ breed: 'corgi' })
        } finally {
            await dog.close()
        }
    })

    it('passthrough: no authoritative provider → transport claim is the identity (no link)', async () => {
        if (!reachable) {
            return
        }
        dog = await startDogServer()
        try {
            const { admission, identities } = build()
            const app = APP()
            const res = await admission.resolve(
                { transport: 'slack', subjectId: 'T:U' },
                { application: app, revision: revFor(app, undefined) }
            )
            expect(res.kind).toBe('passthrough')
            if (res.kind === 'passthrough') {
                const u = await identities.getById(res.transportAgentUserId)
                expect(u?.principal_kind).toBe('slack')
            }
        } finally {
            await dog.close()
        }
    })
})
