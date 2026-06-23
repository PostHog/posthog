/**
 * Integration: the generic Oauth2AuthProvider against the real `dogs` OAuth
 * server + real Postgres stores. Proves the provider half of the flow end to
 * end — initiate → (browser hits /authorize) → complete → resolve → a real
 * call to the protected dog API succeeds — plus token refresh. No agent runner
 * yet; that's the M5 e2e.
 */

import { randomUUID } from 'node:crypto'
import { Pool } from 'pg'
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import {
    HttpClient,
    Oauth2AuthProvider,
    PgIdentityCredentialStore,
    PgIdentityLinkStateStore,
} from '@posthog/agent-shared'
import { reset } from '@posthog/agent-shared/testing'

import { DogServer, startDogServer } from '../harness/dog-oauth-server'

const TEST_DB_URL =
    process.env.AGENT_TEST_DB_URL ?? 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue_test'
const KEY = '01234567890123456789012345678901'
const REDIRECT = 'http://callback.test/link/dogs/callback'

async function isReachable(): Promise<boolean> {
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

const maybeDescribe = process.env.SKIP_PG_TESTS === '1' ? describe.skip : describe

maybeDescribe('Oauth2AuthProvider × dogs IdP (real PG + real HTTP)', () => {
    let pool: Pool
    let reachable = false
    let dog: DogServer

    beforeAll(async () => {
        reachable = await isReachable()
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

    const buildProvider = (
        over: Partial<{ tokenTtlSeconds: number; now: () => number; binding: 'principal' | 'agent' }> = {}
    ): Oauth2AuthProvider => {
        return new Oauth2AuthProvider({
            config: {
                id: 'dogs',
                binding: over.binding,
                authorizeUrl: dog.authorizeUrl,
                tokenUrl: dog.tokenUrl,
                clientId: 'dogs-client',
                scopes: ['read:dog'],
            },
            links: new PgIdentityLinkStateStore(pool),
            credentials: new PgIdentityCredentialStore(pool, { encryptionSaltKeys: KEY }),
            http: new HttpClient({}),
            now: over.now,
        })
    }

    // Simulate the browser visiting the authorize URL: it 302s to our callback
    // with ?code&state. Return those without following the redirect.
    const visitAuthorize = async (authorizeUrl: string): Promise<{ code: string; state: string }> => {
        const res = await fetch(authorizeUrl, { redirect: 'manual' })
        expect(res.status).toBe(302)
        const loc = new URL(res.headers.get('location') ?? '')
        return { code: loc.searchParams.get('code') ?? '', state: loc.searchParams.get('state') ?? '' }
    }

    it('links a principal and the resolved bearer calls the dog API', async () => {
        if (!reachable) {
            return
        }
        dog = await startDogServer()
        try {
            const provider = buildProvider()
            const agentUserId = randomUUID()
            const applicationId = randomUUID()

            // Unlinked → nothing to resolve.
            expect(await provider.resolve({ agentUserId, teamId: 1, applicationId, scopes: [] })).toBeNull()

            const { authorizeUrl, stateId } = await provider.initiate({
                agentUserId,
                teamId: 1,
                applicationId,
                scopes: ['read:dog'],
                redirectUri: REDIRECT,
            })
            const { code, state } = await visitAuthorize(authorizeUrl)
            expect(state).toBe(stateId)

            const done = await provider.complete({ stateId: state, query: { code } })
            expect(done).toEqual({ agentUserId, provider: 'dogs' })

            const cred = await provider.resolve({ agentUserId, teamId: 1, applicationId, scopes: [] })
            expect(cred?.kind).toBe('oauth_bearer')

            // The real proof: the resolved token actually works against the API.
            const token = cred?.kind === 'oauth_bearer' ? cred.token : ''
            const api = await fetch(dog.apiUrl, { headers: { Authorization: `Bearer ${token}` } })
            expect(api.status).toBe(200)
            expect((await api.json()) as { fact: string }).toMatchObject({ breed: 'corgi' })
        } finally {
            await dog.close()
        }
    })

    it('a replayed callback (same state) cannot mint a second credential', async () => {
        if (!reachable) {
            return
        }
        dog = await startDogServer()
        try {
            const provider = buildProvider()
            const agentUserId = randomUUID()
            const applicationId = randomUUID()
            const { authorizeUrl, stateId } = await provider.initiate({
                agentUserId,
                teamId: 1,
                applicationId,
                scopes: ['read:dog'],
                redirectUri: REDIRECT,
            })
            const { code } = await visitAuthorize(authorizeUrl)
            await provider.complete({ stateId, query: { code } })
            await expect(provider.complete({ stateId, query: { code } })).rejects.toThrow('oauth_invalid_state')
        } finally {
            await dog.close()
        }
    })

    it('refreshes an expired access token, and the new token works', async () => {
        if (!reachable) {
            return
        }
        dog = await startDogServer()
        try {
            const agentUserId = randomUUID()
            const applicationId = randomUUID()
            // Link with a normal provider.
            const linker = buildProvider()
            const { authorizeUrl, stateId } = await linker.initiate({
                agentUserId,
                teamId: 1,
                applicationId,
                scopes: ['read:dog'],
                redirectUri: REDIRECT,
            })
            const { code } = await visitAuthorize(authorizeUrl)
            await linker.complete({ stateId, query: { code } })
            const before = await linker.resolve({ agentUserId, teamId: 1, applicationId, scopes: [] })
            const beforeToken = before?.kind === 'oauth_bearer' ? before.token : ''

            // A provider whose clock is far in the future sees the access token
            // as expired and refreshes it.
            const future = buildProvider({ now: () => Date.now() + 10 * 60 * 60 * 1000 })
            const after = await future.resolve({ agentUserId, teamId: 1, applicationId, scopes: [] })
            const afterToken = after?.kind === 'oauth_bearer' ? after.token : ''

            expect(afterToken).not.toBe('')
            expect(afterToken).not.toBe(beforeToken) // rotated
            const api = await fetch(dog.apiUrl, { headers: { Authorization: `Bearer ${afterToken}` } })
            expect(api.status).toBe(200)
        } finally {
            await dog.close()
        }
    })

    it('agent binding resolves the app-scoped credential and refresh-on-expiry persists via putAgentScoped', async () => {
        if (!reachable) {
            return
        }
        dog = await startDogServer()
        try {
            const credentials = new PgIdentityCredentialStore(pool, { encryptionSaltKeys: KEY })
            const applicationId = randomUUID()
            const asker = randomUUID() // an arbitrary asker — agent binding ignores it for resolution

            // Connect the shared credential once. Link a throwaway principal to
            // mint a real dogs-issued refresh token, then copy that credential
            // into the agent-scoped (application, provider) row — agent_user_id
            // NULL — which is what an owner-driven connect would write.
            const linker = buildProvider()
            const owner = randomUUID()
            const { authorizeUrl, stateId } = await linker.initiate({
                agentUserId: owner,
                teamId: 1,
                applicationId,
                scopes: ['read:dog'],
                redirectUri: REDIRECT,
            })
            const { code } = await visitAuthorize(authorizeUrl)
            await linker.complete({ stateId, query: { code } })
            const linked = await credentials.get(owner, 'dogs')
            if (!linked) {
                throw new Error('expected a linked credential to seed from')
            }
            await credentials.putAgentScoped({
                teamId: 1,
                applicationId,
                provider: 'dogs',
                credential: linked.credential,
                scopes: linked.scopes,
            })

            // An agent-bound provider whose clock is far in the future sees the
            // shared access token as expired and refreshes it.
            const agentProvider = buildProvider({ binding: 'agent', now: () => Date.now() + 10 * 60 * 60 * 1000 })
            const before = await credentials.getAgentScoped(applicationId, 'dogs')
            const cred = await agentProvider.resolve({ agentUserId: asker, teamId: 1, applicationId, scopes: [] })
            const token = cred?.kind === 'oauth_bearer' ? cred.token : ''
            expect(token).not.toBe('')

            // The refreshed token works against the real API.
            const api = await fetch(dog.apiUrl, { headers: { Authorization: `Bearer ${token}` } })
            expect(api.status).toBe(200)

            // Refresh persisted to the AGENT-SCOPED row (agent_user_id NULL),
            // rotating its access token — not to a per-principal row.
            const after = await credentials.getAgentScoped(applicationId, 'dogs')
            expect(after?.agentUserId).toBeNull()
            expect(after?.credential.access_token).toBe(token)
            expect(after?.credential.access_token).not.toBe(before?.credential.access_token)
            // No per-principal row was written for the asker.
            expect(await credentials.get(asker, 'dogs')).toBeNull()
        } finally {
            await dog.close()
        }
    })
})
