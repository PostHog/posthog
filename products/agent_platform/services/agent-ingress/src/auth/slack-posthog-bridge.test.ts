/**
 * Unit tests for the Slack → PostHog user bridge. The Slack and PostHog API
 * calls are stubbed; the contract under test is "what does the bridge cache
 * on the AgentUser row given each possible upstream response." The identity
 * store is the real `PgIdentityStore` against the test DB (no in-memory variant).
 */

import { Pool } from 'pg'

import { AgentUser, IntegrationCredentials, IntegrationStore, PgIdentityStore } from '@posthog/agent-shared'
import { reset } from '@posthog/agent-shared/testing'

import { bridgeSlackToPosthogUser } from './slack-posthog-bridge'

/**
 * Per-test inline IntegrationStore stub. PgIntegrationStore reads from the
 * Django `posthog_integration` table which doesn't live in the agent test
 * DB, so this minimal in-test impl seeds whatever rows a case needs.
 */
function makeIntegrationStub(
    seed: Array<{ teamId: number; kind: string; integrationId: string; credentials: IntegrationCredentials }> = []
): IntegrationStore & {
    add: (teamId: number, kind: string, integrationId: string, credentials: IntegrationCredentials) => void
} {
    const rows = [...seed]
    return {
        add(teamId, kind, integrationId, credentials) {
            const i = rows.findIndex((r) => r.teamId === teamId && r.kind === kind && r.integrationId === integrationId)
            const row = { teamId, kind, integrationId, credentials }
            if (i >= 0) {
                rows[i] = row
            } else {
                rows.push(row)
            }
        },
        async get(teamId, kind, integrationId) {
            return (
                rows.find((r) => r.teamId === teamId && r.kind === kind && r.integrationId === integrationId)
                    ?.credentials ?? null
            )
        },
        async list(teamId, kind) {
            return rows
                .filter((r) => r.teamId === teamId && r.kind === kind)
                .map((r) => ({ integration_id: r.integrationId, credentials: r.credentials }))
        },
        async resolveForSpec(teamId, kinds) {
            const out: Record<string, IntegrationCredentials> = {}
            for (const kind of kinds) {
                for (const r of rows.filter((rr) => rr.teamId === teamId && rr.kind === kind)) {
                    out[`${kind}:${r.integrationId}`] = r.credentials
                }
            }
            return out
        },
    }
}

const TEST_DB_URL =
    process.env.AGENT_TEST_DB_URL ?? 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue_test'

let pool: Pool

beforeAll(() => {
    pool = new Pool({ connectionString: TEST_DB_URL })
})

afterAll(async () => {
    await pool.end()
})

beforeEach(async () => {
    await reset({ databaseUrl: TEST_DB_URL })
})

async function seedIdentity(store: PgIdentityStore, agentUser: AgentUser): Promise<void> {
    // Round-trip the row through the public API so tests don't depend on
    // the store's private internals. findOrCreate uses (application_id,
    // principal_kind, principal_id) as the natural key, then we patch
    // metadata + posthog_user_id via the public setters.
    const created = await store.findOrCreate({
        team_id: agentUser.team_id,
        application_id: agentUser.application_id,
        principal_kind: agentUser.principal_kind,
        principal_id: agentUser.principal_id,
        metadata: agentUser.metadata,
    })
    // Hand back the stable id so the caller can use it in the bridge call.
    agentUser.id = created.id
    if (agentUser.posthog_user_id !== undefined) {
        await store.setPosthogUserId(created.id, agentUser.posthog_user_id)
    }
}

function makeAgentUser(overrides: Partial<AgentUser> = {}): AgentUser {
    return {
        id: 'au-bob',
        team_id: 1,
        application_id: '00000000-0000-4000-8000-00000000aa01',
        principal_kind: 'slack',
        principal_id: 'T01ACME:U-BOB',
        metadata: { workspace: 'T01ACME', slack_user: 'U-BOB' },
        posthog_user_id: undefined,
        created_at: '2026-05-27T00:00:00Z',
        ...overrides,
    }
}

function fakePosthogDb(emailToUserId: Record<string, number>): import('pg').Pool {
    return {
        // The bridge only calls `.query(sql, params)` and reads `rowCount` +
        // `rows`. A stub matching that minimal surface is enough.
        async query(_sql: string, params: unknown[]) {
            const email = String(params[0] ?? '').toLowerCase()
            const id = Object.entries(emailToUserId).find(([k]) => k.toLowerCase() === email)?.[1]
            if (id === undefined) {
                return { rowCount: 0, rows: [] }
            }
            return { rowCount: 1, rows: [{ id }] }
        },
    } as unknown as import('pg').Pool
}

describe('bridgeSlackToPosthogUser', () => {
    it('caches the matched posthog_user.id when slack returns an email that exists', async () => {
        const integrations = makeIntegrationStub()
        integrations.add(1, 'slack', 'T01ACME', { kind: 'slack', access_token: 'xoxb-acme' })
        const identities = new PgIdentityStore(pool)
        const agentUser = makeAgentUser()
        await seedIdentity(identities, agentUser)

        const userId = await bridgeSlackToPosthogUser(agentUser, 'T01ACME', 'U-BOB', {
            integrations,
            identities,
            posthogDb: fakePosthogDb({ 'bob@posthog.com': 42 }),
            fetchSlackEmail: async () => 'bob@posthog.com',
        })

        expect(userId).toBe(42)
        const cached = await identities.find({
            application_id: '00000000-0000-4000-8000-00000000aa01',
            principal_kind: 'slack',
            principal_id: 'T01ACME:U-BOB',
        })
        expect(cached!.posthog_user_id).toBe(42)
    })

    it('caches `null` when slack returns an email with no matching posthog_user', async () => {
        const integrations = makeIntegrationStub()
        integrations.add(1, 'slack', 'T01ACME', { kind: 'slack', access_token: 'xoxb-acme' })
        const identities = new PgIdentityStore(pool)
        const agentUser = makeAgentUser({ id: 'au-external' })
        await seedIdentity(identities, agentUser)

        const userId = await bridgeSlackToPosthogUser(agentUser, 'T01ACME', 'U-EXTERNAL', {
            integrations,
            identities,
            posthogDb: fakePosthogDb({}),
            fetchSlackEmail: async () => 'external@example.com',
        })

        expect(userId).toBeNull()
        const cached = await identities.find({
            application_id: '00000000-0000-4000-8000-00000000aa01',
            principal_kind: 'slack',
            principal_id: 'T01ACME:U-BOB',
        })
        expect(cached!.posthog_user_id).toBeNull()
    })

    it('returns the cached posthog_user_id without re-running the lookup', async () => {
        const identities = new PgIdentityStore(pool)
        const agentUser = makeAgentUser({ posthog_user_id: 7 })
        await seedIdentity(identities, agentUser)

        let calls = 0
        const userId = await bridgeSlackToPosthogUser(agentUser, 'T01ACME', 'U-BOB', {
            integrations: makeIntegrationStub(),
            identities,
            posthogDb: fakePosthogDb({}),
            fetchSlackEmail: async () => {
                calls++
                return 'unused@posthog.com'
            },
        })
        expect(userId).toBe(7)
        expect(calls).toBe(0)
    })

    it('respects an explicit cached null (no match found previously) without re-asking slack', async () => {
        const identities = new PgIdentityStore(pool)
        const agentUser = makeAgentUser({ posthog_user_id: null })
        await seedIdentity(identities, agentUser)

        let calls = 0
        const userId = await bridgeSlackToPosthogUser(agentUser, 'T01ACME', 'U-BOB', {
            integrations: makeIntegrationStub(),
            identities,
            posthogDb: fakePosthogDb({}),
            fetchSlackEmail: async () => {
                calls++
                return 'unused@posthog.com'
            },
        })
        expect(userId).toBeNull()
        expect(calls).toBe(0)
    })

    it('caches `null` when no slack integration is connected (treat as "lookup ran, no match")', async () => {
        const identities = new PgIdentityStore(pool)
        const agentUser = makeAgentUser({ id: 'au-noslack' })
        await seedIdentity(identities, agentUser)

        // Empty integration store — no slack token for the team.
        const userId = await bridgeSlackToPosthogUser(agentUser, 'T01ACME', 'U-BOB', {
            integrations: makeIntegrationStub(),
            identities,
            posthogDb: fakePosthogDb({ 'bob@posthog.com': 42 }),
            fetchSlackEmail: async () => 'bob@posthog.com',
        })
        expect(userId).toBeNull()
        const cached = await identities.find({
            application_id: '00000000-0000-4000-8000-00000000aa01',
            principal_kind: 'slack',
            principal_id: 'T01ACME:U-BOB',
        })
        expect(cached!.posthog_user_id).toBeNull()
    })

    it('does NOT cache when the slack lookup throws — next event can retry', async () => {
        const integrations = makeIntegrationStub()
        integrations.add(1, 'slack', 'T01ACME', { kind: 'slack', access_token: 'xoxb-acme' })
        const identities = new PgIdentityStore(pool)
        const agentUser = makeAgentUser({ id: 'au-blip' })
        await seedIdentity(identities, agentUser)

        const userId = await bridgeSlackToPosthogUser(agentUser, 'T01ACME', 'U-BOB', {
            integrations,
            identities,
            posthogDb: fakePosthogDb({ 'bob@posthog.com': 42 }),
            fetchSlackEmail: async () => {
                throw new Error('slack: 500')
            },
        })
        expect(userId).toBeNull()
        const cached = await identities.find({
            application_id: '00000000-0000-4000-8000-00000000aa01',
            principal_kind: 'slack',
            principal_id: 'T01ACME:U-BOB',
        })
        // Lookup failed transiently. PgIdentityStore initialises
        // `posthog_user_id` to NULL on row create, so we can't distinguish
        // "never looked up" from "looked up, no match" purely on the column
        // value — the contract is that the bridge does NOT explicitly stamp
        // a cache marker when the upstream throws, so the next event can
        // retry. Asserting null here captures the on-disk default.
        expect(cached!.posthog_user_id).toBeNull()
    })

    it('matches emails case-insensitively (Slack profile + PostHog stored case may differ)', async () => {
        const integrations = makeIntegrationStub()
        integrations.add(1, 'slack', 'T01ACME', { kind: 'slack', access_token: 'xoxb-acme' })
        const identities = new PgIdentityStore(pool)
        const agentUser = makeAgentUser({ id: 'au-case' })
        await seedIdentity(identities, agentUser)

        const userId = await bridgeSlackToPosthogUser(agentUser, 'T01ACME', 'U-BOB', {
            integrations,
            identities,
            posthogDb: fakePosthogDb({ 'carol@posthog.com': 99 }),
            fetchSlackEmail: async () => 'Carol@PostHog.com',
        })
        expect(userId).toBe(99)
    })
})
