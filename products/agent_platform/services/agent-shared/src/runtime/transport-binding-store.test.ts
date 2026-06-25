/**
 * Real-PG tests for the transport→canonical-identity binding store. The
 * (application, transport) uniqueness + idempotent re-bind is what makes "auth
 * once, every future turn resolves the same identity" durable, so it's proven
 * against Postgres, not a mock. The in-memory impl is exercised via admission.test.ts.
 */

import { randomUUID } from 'node:crypto'
import { Pool } from 'pg'
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { isReachable, reset } from '@posthog/agent-shared/testing'

import { PgTransportBindingStore } from './transport-binding-store'

const TEST_DB_URL =
    process.env.AGENT_TEST_DB_URL ?? 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue_test'

const maybeDescribe = process.env.SKIP_PG_TESTS === '1' ? describe.skip : describe

maybeDescribe('PgTransportBindingStore (real PG)', () => {
    let pool: Pool
    let reachable = false
    let store: PgTransportBindingStore
    const APP = randomUUID()

    beforeAll(async () => {
        reachable = await isReachable(TEST_DB_URL)
        if (!reachable) {
            return
        }
        pool = new Pool({ connectionString: TEST_DB_URL, max: 4 })
        store = new PgTransportBindingStore(pool)
    })

    beforeEach(async () => {
        if (reachable) {
            await reset({ databaseUrl: TEST_DB_URL })
        }
    })

    afterAll(async () => {
        await pool?.end().catch(() => undefined)
    })

    it('binds, finds, and is null before binding', async () => {
        if (!reachable) {
            return
        }
        const transport = randomUUID()
        const canonical = randomUUID()
        expect(await store.find(APP, transport)).toBeNull()

        const bound = await store.bind({
            teamId: 1,
            applicationId: APP,
            transportAgentUserId: transport,
            canonicalAgentUserId: canonical,
            provider: 'work',
        })
        expect(bound.canonicalAgentUserId).toBe(canonical)

        const found = await store.find(APP, transport)
        expect(found?.canonicalAgentUserId).toBe(canonical)
        expect(found?.provider).toBe('work')
    })

    it('re-binding the same transport replaces the canonical id, keeps created_at', async () => {
        if (!reachable) {
            return
        }
        const transport = randomUUID()
        const first = await store.bind({
            teamId: 1,
            applicationId: APP,
            transportAgentUserId: transport,
            canonicalAgentUserId: randomUUID(),
            provider: 'work',
        })
        const newCanonical = randomUUID()
        const second = await store.bind({
            teamId: 1,
            applicationId: APP,
            transportAgentUserId: transport,
            canonicalAgentUserId: newCanonical,
            provider: 'work',
        })
        expect(second.canonicalAgentUserId).toBe(newCanonical)
        expect(second.createdAt).toBe(first.createdAt) // idempotent upsert preserves created_at
        // Still exactly one row for this transport.
        const all = await store.listForCanonical(APP, newCanonical)
        expect(all).toHaveLength(1)
    })

    it('lists many transports for one canonical identity (one identity, many transports)', async () => {
        if (!reachable) {
            return
        }
        const canonical = randomUUID()
        const slack = randomUUID()
        const discord = randomUUID()
        await store.bind({
            teamId: 1,
            applicationId: APP,
            transportAgentUserId: slack,
            canonicalAgentUserId: canonical,
            provider: 'work',
        })
        await store.bind({
            teamId: 1,
            applicationId: APP,
            transportAgentUserId: discord,
            canonicalAgentUserId: canonical,
            provider: 'work',
        })

        const all = await store.listForCanonical(APP, canonical)
        expect(all.map((b) => b.transportAgentUserId).sort()).toEqual([slack, discord].sort())
    })

    it('unbind removes the binding (unlink)', async () => {
        if (!reachable) {
            return
        }
        const transport = randomUUID()
        await store.bind({
            teamId: 1,
            applicationId: APP,
            transportAgentUserId: transport,
            canonicalAgentUserId: randomUUID(),
            provider: 'work',
        })
        await store.unbind(APP, transport)
        expect(await store.find(APP, transport)).toBeNull()
    })
})
