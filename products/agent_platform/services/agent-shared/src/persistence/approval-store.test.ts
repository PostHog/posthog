import { randomUUID } from 'node:crypto'
import { Pool } from 'pg'

import { reset } from '@posthog/agent-shared/testing'

import { AssistantMessageRecord } from '../spec/spec'
import { ApprovalStore, effectiveApprovalType, hashCanonicalArgs, UpsertApprovalRequestInput } from './approval-store'
import { PgApprovalStore } from './pg-approval-store'

describe('effectiveApprovalType', () => {
    it.each([
        ['new principal scope', { type: 'principal', allow_edit: false }, 'principal'],
        ['new agent scope', { type: 'agent', allow_edit: true }, 'agent'],
        ['legacy team_admins → agent', { approvers: ['team_admins'] }, 'agent'],
        ['legacy session_principal → principal', { approvers: ['session_principal'] }, 'principal'],
        ['empty / unknown → principal', {}, 'principal'],
    ])('%s', (_label, scope, expected) => {
        expect(effectiveApprovalType(scope as never)).toBe(expected)
    })
})

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

function fauxAssistantMessage(): AssistantMessageRecord {
    return {
        role: 'assistant',
        content: [{ type: 'text', text: 'I will run delete with id=42' }],
        timestamp: Date.now(),
    }
}

const DEFAULT_SESSION_ID = '00000000-0000-4000-8000-000000005e51'
const DEFAULT_APP_ID = '00000000-0000-4000-8000-000000005a91'
const DEFAULT_REV_ID = '00000000-0000-4000-8000-000000005ee1'
const SESSION_ID_S1 = '00000000-0000-4000-8000-0000000051f1'
const SESSION_ID_S2 = '00000000-0000-4000-8000-0000000052f2'

function buildInput(overrides: Partial<UpsertApprovalRequestInput> = {}): UpsertApprovalRequestInput {
    return {
        id: randomUUID(),
        session_id: DEFAULT_SESSION_ID,
        application_id: DEFAULT_APP_ID,
        team_id: 1,
        revision_id: DEFAULT_REV_ID,
        turn: 1,
        tool_call_id: 'tc_abc',
        tool_name: '@posthog/team-delete',
        proposed_args: { team_id: 42 },
        assistant_message: fauxAssistantMessage(),
        approver_scope: {
            type: 'agent',
            allow_edit: false,
        },
        expires_at: new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString(),
        ...overrides,
    }
}

/**
 * Seed the parent `agent_session` rows so the approval table's FK
 * (`agent_tool_approval_request.session_id → agent_session.id`) holds. The
 * test uses a handful of fixed uuids; pre-seed them after each schema reset.
 */
async function seedSessions(sessionIds: string[]): Promise<void> {
    for (const id of sessionIds) {
        await pool.query(
            `INSERT INTO agent_session
                (id, application_id, revision_id, team_id, state, conversation, pending_inputs)
             VALUES ($1, $2, $3, 1, 'queued', '[]'::jsonb, '[]'::jsonb)
             ON CONFLICT (id) DO NOTHING`,
            [id, DEFAULT_APP_ID, DEFAULT_REV_ID]
        )
    }
}

describe('ApprovalStore (PG)', () => {
    let store: ApprovalStore

    beforeEach(async () => {
        store = new PgApprovalStore(pool)
        await seedSessions([DEFAULT_SESSION_ID, SESSION_ID_S1, SESSION_ID_S2])
    })

    describe('hashCanonicalArgs', () => {
        it('produces identical hashes for object-key reorderings', () => {
            const a = hashCanonicalArgs({ a: 1, b: { z: 1, y: 2 } })
            const b = hashCanonicalArgs({ b: { y: 2, z: 1 }, a: 1 })
            expect(a.equals(b)).toBe(true)
        })

        it('differs when values change', () => {
            const a = hashCanonicalArgs({ team_id: 42 })
            const b = hashCanonicalArgs({ team_id: 43 })
            expect(a.equals(b)).toBe(false)
        })
    })

    describe('upsertQueued idempotency', () => {
        it('returns the existing queued row for the same canonical args', async () => {
            const first = await store.upsertQueued(buildInput())
            expect(first.deduped).toBe(false)

            const second = await store.upsertQueued(
                buildInput({ proposed_args: { team_id: 42 }, tool_call_id: 'tc_other' })
            )
            expect(second.deduped).toBe(true)
            expect(second.request.id).toBe(first.request.id)
        })

        it('treats reordered keys as the same args', async () => {
            await store.upsertQueued(buildInput({ proposed_args: { x: 1, y: 2 } }))
            const second = await store.upsertQueued(buildInput({ proposed_args: { y: 2, x: 1 } }))
            expect(second.deduped).toBe(true)
        })

        it('creates a new row when args differ', async () => {
            const a = await store.upsertQueued(buildInput({ proposed_args: { team_id: 42 } }))
            const b = await store.upsertQueued(buildInput({ proposed_args: { team_id: 43 } }))
            expect(b.deduped).toBe(false)
            expect(b.request.id).not.toBe(a.request.id)
        })

        it('after rejection, re-issuing the same args creates a fresh row (not deduped)', async () => {
            const first = await store.upsertQueued(buildInput())
            await store.markRejected(first.request.id, {
                decided_by: '00000000-0000-4000-8000-0000000000a1',
                decided_at: new Date().toISOString(),
                reason: 'no',
            })
            const second = await store.upsertQueued(buildInput())
            expect(second.deduped).toBe(false)
            expect(second.request.id).not.toBe(first.request.id)
        })
    })

    describe('decision transitions', () => {
        it('markApproving only fires from queued', async () => {
            const { request } = await store.upsertQueued(buildInput())
            const ok = await store.markApproving(request.id, {
                decided_by: '00000000-0000-4000-8000-0000000000a1',
                decided_at: new Date().toISOString(),
            })
            expect(ok?.state).toBe('approving')

            // Second attempt is a no-op.
            const again = await store.markApproving(request.id, {
                decided_by: '00000000-0000-4000-8000-0000000000a1',
                decided_at: new Date().toISOString(),
            })
            expect(again).toBeNull()
        })

        it('markDispatched maps outcome.error to dispatched_failed', async () => {
            const { request } = await store.upsertQueued(buildInput())
            await store.markApproving(request.id, {
                decided_by: '00000000-0000-4000-8000-0000000000a1',
                decided_at: new Date().toISOString(),
            })
            const failed = await store.markDispatched(request.id, { error: 'kaboom' })
            expect(failed?.state).toBe('dispatched_failed')
            expect(failed?.dispatch_outcome).toEqual({ error: 'kaboom' })
        })

        it('markDispatched with result lands as dispatched', async () => {
            const { request } = await store.upsertQueued(buildInput())
            await store.markApproving(request.id, {
                decided_by: '00000000-0000-4000-8000-0000000000a1',
                decided_at: new Date().toISOString(),
            })
            const done = await store.markDispatched(request.id, { result: { ok: true } })
            expect(done?.state).toBe('dispatched')
            expect(done?.dispatch_outcome).toEqual({ result: { ok: true } })
        })

        it('markRejected stamps reason', async () => {
            const { request } = await store.upsertQueued(buildInput())
            const rejected = await store.markRejected(request.id, {
                decided_by: '00000000-0000-4000-8000-0000000000a1',
                decided_at: new Date().toISOString(),
                reason: 'amount too high',
            })
            expect(rejected?.state).toBe('rejected')
            expect(rejected?.decision_reason).toBe('amount too high')
        })
    })

    describe('expireQueued', () => {
        it('flips only queued rows past expires_at', async () => {
            const past = new Date(Date.now() - 1000).toISOString()
            const future = new Date(Date.now() + 60_000).toISOString()
            const expired = await store.upsertQueued(buildInput({ expires_at: past }))
            await store.upsertQueued(buildInput({ proposed_args: { team_id: 99 }, expires_at: future }))

            const flipped = await store.expireQueued(new Date().toISOString())
            expect(flipped).toHaveLength(1)
            expect(flipped[0].id).toBe(expired.request.id)
            expect((await store.get(expired.request.id))?.state).toBe('expired')
        })
    })

    describe('listings', () => {
        it('lists by session, scoped to that session only', async () => {
            const a = await store.upsertQueued(buildInput({ session_id: SESSION_ID_S1, proposed_args: { team_id: 1 } }))
            const b = await store.upsertQueued(buildInput({ session_id: SESSION_ID_S1, proposed_args: { team_id: 2 } }))
            await store.upsertQueued(buildInput({ session_id: SESSION_ID_S2, proposed_args: { team_id: 3 } }))

            // Ordering across rows created in the same tick is implementation-
            // defined (the Pg impl orders by created_at DESC; ties break
            // however Pg likes). Assert membership, not order.
            const ids = (await store.listBySession(SESSION_ID_S1)).map((r) => r.id).sort()
            expect(ids).toEqual([a.request.id, b.request.id].sort())
        })

        it('filters listings by state', async () => {
            const { request } = await store.upsertQueued(buildInput({ session_id: SESSION_ID_S1 }))
            await store.markRejected(request.id, {
                decided_by: '00000000-0000-4000-8000-0000000000a1',
                decided_at: new Date().toISOString(),
            })
            await store.upsertQueued(buildInput({ session_id: SESSION_ID_S1, proposed_args: { team_id: 99 } }))

            const queued = await store.listBySession(SESSION_ID_S1, { state: 'queued' })
            expect(queued).toHaveLength(1)
            expect(queued[0].state).toBe('queued')

            const rejected = await store.listBySession(SESSION_ID_S1, { state: 'rejected' })
            expect(rejected).toHaveLength(1)
            expect(rejected[0].state).toBe('rejected')
        })
    })

    describe('getForApplication (tenant-scoped read)', () => {
        it.each<[string, string, 'resolves' | 'null']>([
            ['owning application id', DEFAULT_APP_ID, 'resolves'],
            ['mismatched application id (no cross-tenant read)', '00000000-0000-4000-8000-0000000060ff', 'null'],
        ])('%s → %s', async (_label, appId, expected) => {
            const { request } = await store.upsertQueued(buildInput())
            const result = await store.getForApplication(request.id, appId)
            if (expected === 'resolves') {
                expect(result?.id).toBe(request.id)
            } else {
                expect(result).toBeNull()
            }
        })
    })
})
