/**
 * Real-PG tests for the OAuth link-state store. The single-use `consume`
 * contract is a security primitive (a replayed callback must not mint a second
 * credential), so it's worth proving against Postgres' atomicity, not a mock.
 */

import { randomUUID } from 'node:crypto'
import { Pool } from 'pg'
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { isReachable, reset } from '@posthog/agent-shared/testing'

import { PgIdentityLinkStateStore } from '../runtime/identity-link-state-store'

const TEST_DB_URL =
    process.env.AGENT_TEST_DB_URL ?? 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue_test'

const maybeDescribe = process.env.SKIP_PG_TESTS === '1' ? describe.skip : describe

maybeDescribe('PgIdentityLinkStateStore (real PG)', () => {
    let pool: Pool
    let reachable = false
    let store: PgIdentityLinkStateStore

    beforeAll(async () => {
        reachable = await isReachable(TEST_DB_URL)
        if (!reachable) {
            return
        }
        pool = new Pool({ connectionString: TEST_DB_URL, max: 4 })
        store = new PgIdentityLinkStateStore(pool)
    })

    beforeEach(async () => {
        if (reachable) {
            await reset({ databaseUrl: TEST_DB_URL })
        }
    })

    afterAll(async () => {
        await pool?.end().catch(() => undefined)
    })

    const create = (ttlMs?: number): Promise<string> =>
        store.create({
            teamId: 1,
            applicationId: randomUUID(),
            agentUserId: randomUUID(),
            provider: 'dogs',
            scopes: ['read:dog'],
            codeVerifier: 'verifier-xyz',
            redirectUri: 'https://x/cb',
            ttlMs,
        })

    it('consume returns the row exactly once', async () => {
        if (!reachable) {
            return
        }
        const id = await create()
        const first = await store.consume(id)
        expect(first?.provider).toBe('dogs')
        expect(first?.codeVerifier).toBe('verifier-xyz')
        expect(first?.scopes).toEqual(['read:dog'])

        // Replayed callback → no row.
        expect(await store.consume(id)).toBeNull()
    })

    it('consume returns null for an unknown id', async () => {
        if (!reachable) {
            return
        }
        expect(await store.consume(randomUUID())).toBeNull()
    })

    it('consume returns null once expired', async () => {
        if (!reachable) {
            return
        }
        const id = await create(-1000) // already expired
        expect(await store.consume(id)).toBeNull()
    })
})
