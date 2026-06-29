/**
 * Integration: the @posthog/identity-fetch native tool + ctx.identity gate
 * against the real dogs IdP + real PG stores. Proves the runner-side capability
 * (gate → auth_required link → link → resolve → real authed API call) at the
 * tool boundary, before the full ingress+runner e2e (M5).
 */

import { randomUUID } from 'node:crypto'
import { Pool } from 'pg'
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import {
    buildIdentityRegistry,
    createToolIdentity,
    HttpClient,
    type IdentityProviderConfig,
    MapIdentityProviderRegistry,
    PgIdentityCredentialStore,
    PgIdentityLinkStateStore,
    type ToolContext,
} from '@posthog/agent-shared'
import { reset } from '@posthog/agent-shared/testing'
import { getNativeTool } from '@posthog/agent-tools'

import { DogServer, startDogServer } from '../harness/dog-oauth-server'

const TEST_DB_URL =
    process.env.AGENT_TEST_DB_URL ?? 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue_test'
const KEY = '01234567890123456789012345678901'

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

maybeDescribe('@posthog/identity-fetch × dogs (real PG + HTTP)', () => {
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

    const visitAuthorize = async (authorizeUrl: string): Promise<{ code: string; state: string }> => {
        const res = await fetch(authorizeUrl, { redirect: 'manual' })
        const loc = new URL(res.headers.get('location') ?? '')
        return { code: loc.searchParams.get('code') ?? '', state: loc.searchParams.get('state') ?? '' }
    }

    it('returns auth_required when unlinked, then fetches the API after linking', async () => {
        if (!reachable) {
            return
        }
        dog = await startDogServer()
        try {
            const agentUserId = randomUUID()
            const applicationId = randomUUID()
            const config: IdentityProviderConfig = {
                kind: 'oauth2',
                id: 'dogs',
                binding: 'principal',
                authorize_url: dog.authorizeUrl,
                token_url: dog.tokenUrl,
                client_id: 'dogs-client',
                scopes: ['read:dog'],
            }
            const registry = buildIdentityRegistry([config], {
                links: new PgIdentityLinkStateStore(pool),
                credentials: new PgIdentityCredentialStore(pool, { encryptionSaltKeys: KEY }),
                http: new HttpClient({}),
                secret: () => undefined,
            })
            const identity = createToolIdentity({
                registry,
                agentUserId,
                teamId: 1,
                applicationId,
                redirectUriFor: (p) => `http://callback.test/link/${p}/callback`,
            })
            const ctx: ToolContext = {
                teamId: 1,
                applicationId,
                sessionId: randomUUID(),
                secret: () => undefined,
                secretAllowedHosts: () => undefined,
                log: () => undefined,
                identity,
                http: new HttpClient({}),
                posthogApiBaseUrl: '',
            }
            const tool = getNativeTool('@posthog/identity-fetch')

            // 1) Unlinked → auth_required with a link.
            const gated = (await tool.run({ provider: 'dogs', url: dog.apiUrl }, ctx)) as {
                auth_required?: { provider: string; authorize_url: string }
            }
            expect(gated.auth_required?.provider).toBe('dogs')
            expect(gated.auth_required?.authorize_url).toContain(dog.baseUrl)

            // 2) Complete the link (browser → callback).
            const { code, state } = await visitAuthorize(gated.auth_required!.authorize_url)
            await registry.require('dogs').complete({ stateId: state, query: { code } })

            // 3) Linked → the tool calls the dog API as the user.
            const ok = (await tool.run({ provider: 'dogs', url: dog.apiUrl }, ctx)) as {
                status?: number
                body?: { breed?: string }
            }
            expect(ok.status).toBe(200)
            expect(ok.body?.breed).toBe('corgi')
        } finally {
            await dog.close()
        }
    })

    it('fails closed in a shared participant session (T1)', async () => {
        // No DB/IdP needed: the shared-session guard short-circuits resolve.
        const identity = createToolIdentity({
            registry: new MapIdentityProviderRegistry([]),
            agentUserId: 'owner',
            teamId: 1,
            applicationId: randomUUID(),
            redirectUriFor: (p) => `http://callback.test/${p}`,
            unavailableReason: 'shared_session_unsupported',
        })
        const ctx: ToolContext = {
            teamId: 1,
            applicationId: randomUUID(),
            sessionId: randomUUID(),
            secret: () => undefined,
            secretAllowedHosts: () => undefined,
            log: () => undefined,
            identity,
            http: new HttpClient({}),
            posthogApiBaseUrl: '',
        }
        await expect(
            getNativeTool('@posthog/identity-fetch').run({ provider: 'dogs', url: 'http://x/api' }, ctx)
        ).rejects.toThrow('shared_session_unsupported')
    })

    it('refuses to send the bearer to a host outside the provider', async () => {
        if (!reachable) {
            return
        }
        dog = await startDogServer()
        try {
            const agentUserId = randomUUID()
            const applicationId = randomUUID()
            const config: IdentityProviderConfig = {
                kind: 'oauth2',
                id: 'dogs',
                binding: 'principal',
                authorize_url: dog.authorizeUrl,
                token_url: dog.tokenUrl,
                client_id: 'dogs-client',
                scopes: ['read:dog'],
            }
            const registry = buildIdentityRegistry([config], {
                links: new PgIdentityLinkStateStore(pool),
                credentials: new PgIdentityCredentialStore(pool, { encryptionSaltKeys: KEY }),
                http: new HttpClient({}),
                secret: () => undefined,
            })
            const identity = createToolIdentity({
                registry,
                agentUserId,
                teamId: 1,
                applicationId,
                redirectUriFor: (p) => `http://callback.test/link/${p}/callback`,
            })
            const ctx: ToolContext = {
                teamId: 1,
                applicationId,
                sessionId: randomUUID(),
                secret: () => undefined,
                secretAllowedHosts: () => undefined,
                log: () => undefined,
                identity,
                http: new HttpClient({}),
                posthogApiBaseUrl: '',
            }
            // Link first.
            const init = await registry.require('dogs').initiate({
                agentUserId,
                teamId: 1,
                applicationId,
                scopes: ['read:dog'],
                redirectUri: 'http://callback.test/cb',
            })
            const { code, state } = await visitAuthorize(init.authorizeUrl)
            await registry.require('dogs').complete({ stateId: state, query: { code } })

            const tool = getNativeTool('@posthog/identity-fetch')
            await expect(tool.run({ provider: 'dogs', url: 'https://evil.example.com/steal' }, ctx)).rejects.toThrow(
                'identity_host_not_allowed'
            )
        } finally {
            await dog.close()
        }
    })
})
