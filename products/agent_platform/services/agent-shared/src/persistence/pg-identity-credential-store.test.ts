/**
 * Real-Postgres tests for the persistent linked-credential store. Also the
 * proof that the hand-written `agent_identity_credential` SCHEMA_SQL snapshot
 * (test-reset.ts) matches what the store's SQL expects. Skips if the local
 * test DB is unreachable, same as pg-impls.test.ts.
 */

import { randomUUID } from 'node:crypto'
import { Pool } from 'pg'
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { isReachable, reset } from '@posthog/agent-shared/testing'

import { PgIdentityCredentialStore, StoredCredential } from '../runtime/identity-credential-store'

const TEST_DB_URL =
    process.env.AGENT_TEST_DB_URL ?? 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue_test'
const KEY = '01234567890123456789012345678901' // 32-byte UTF-8, matches the harness

const cred = (over: Partial<StoredCredential> = {}): StoredCredential => ({
    access_token: 'at-1',
    refresh_token: 'rt-1',
    token_type: 'bearer',
    ...over,
})

const maybeDescribe = process.env.SKIP_PG_TESTS === '1' ? describe.skip : describe

// agent_user_id is a uuid column — use real UUIDs, not labels.
const USER_A = randomUUID()
const USER_B = randomUUID()

maybeDescribe('PgIdentityCredentialStore (real PG)', () => {
    let pool: Pool
    let reachable = false
    let store: PgIdentityCredentialStore

    beforeAll(async () => {
        reachable = await isReachable(TEST_DB_URL)
        if (!reachable) {
            // eslint-disable-next-line no-console
            console.warn(`[pg-identity-credential-store.test] ${TEST_DB_URL} unreachable — skipping`)
            return
        }
        pool = new Pool({ connectionString: TEST_DB_URL, max: 4 })
        store = new PgIdentityCredentialStore(pool, { encryptionSaltKeys: KEY })
    })

    beforeEach(async () => {
        if (reachable) {
            await reset({ databaseUrl: TEST_DB_URL })
        }
    })

    afterAll(async () => {
        await pool?.end().catch(() => undefined)
    })

    const put = (over: Partial<Parameters<PgIdentityCredentialStore['put']>[0]> = {}): Promise<void> =>
        store.put({
            teamId: 1,
            applicationId: randomUUID(),
            agentUserId: USER_A,
            provider: 'dogs',
            credential: cred(),
            ...over,
        })

    it('round-trips an encrypted credential and is opaque at rest', async () => {
        if (!reachable) {
            return
        }
        await put({ agentUserId: USER_A, credential: cred({ access_token: 'secret-token' }), scopes: ['read:dog'] })

        const got = await store.get(USER_A, 'dogs')
        expect(got?.credential.access_token).toBe('secret-token')
        expect(got?.scopes).toEqual(['read:dog'])

        // Ciphertext on disk must not contain the plaintext token.
        const raw = await pool.query('SELECT encrypted_credentials FROM agent_identity_credential')
        expect(raw.rows[0].encrypted_credentials).not.toContain('secret-token')
    })

    it('returns null for an unlinked (user, provider)', async () => {
        if (!reachable) {
            return
        }
        expect(await store.get(randomUUID(), 'dogs')).toBeNull()
    })

    it('upserts on (agent_user, provider) — last write wins, single row', async () => {
        if (!reachable) {
            return
        }
        await put({ credential: cred({ access_token: 'first' }) })
        await put({ credential: cred({ access_token: 'second' }) })

        const got = await store.get(USER_A, 'dogs')
        expect(got?.credential.access_token).toBe('second')
        const count = await pool.query('SELECT count(*) FROM agent_identity_credential')
        expect(Number(count.rows[0].count)).toBe(1)
    })

    it('keeps providers and users independent', async () => {
        if (!reachable) {
            return
        }
        await put({ agentUserId: USER_A, provider: 'dogs', credential: cred({ access_token: 'a-dogs' }) })
        await put({ agentUserId: USER_A, provider: 'posthog', credential: cred({ access_token: 'a-ph' }) })
        await put({ agentUserId: USER_B, provider: 'dogs', credential: cred({ access_token: 'b-dogs' }) })

        expect((await store.get(USER_A, 'dogs'))?.credential.access_token).toBe('a-dogs')
        expect((await store.get(USER_A, 'posthog'))?.credential.access_token).toBe('a-ph')
        expect((await store.get(USER_B, 'dogs'))?.credential.access_token).toBe('b-dogs')
    })

    it('revoke hides the credential; a fresh put reactivates it', async () => {
        if (!reachable) {
            return
        }
        await put()
        await store.revoke(USER_A, 'dogs')
        expect(await store.get(USER_A, 'dogs')).toBeNull()

        await put({ credential: cred({ access_token: 'relinked' }) })
        expect((await store.get(USER_A, 'dogs'))?.credential.access_token).toBe('relinked')
    })

    it('remove hard-deletes', async () => {
        if (!reachable) {
            return
        }
        await put()
        await store.remove(USER_A, 'dogs')
        const count = await pool.query('SELECT count(*) FROM agent_identity_credential')
        expect(Number(count.rows[0].count)).toBe(0)
    })
})
