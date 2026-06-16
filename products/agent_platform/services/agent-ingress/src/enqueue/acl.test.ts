/**
 * Unit tests for the grant/decline + authorize helpers exposed by acl.ts.
 *
 * The Slack interactivity handler (services/agent-ingress/src/triggers/slack.ts)
 * and the future REST grant endpoint both call through these helpers, so
 * the contract is shared. End-to-end coverage of the Slack interactivity
 * path lives in agent-tests under cases/slack-elevation-interactivity.test.ts.
 */

import { Pool } from 'pg'

import {
    AgentSession,
    EMPTY_USAGE_TOTAL,
    PendingElevationRequest,
    PgSessionQueue,
    SessionPrincipal,
} from '@posthog/agent-shared'
import { reset } from '@posthog/agent-shared/testing'

import { applyElevationDecline, applyElevationGrant, authorizeGrant } from './acl'

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

const ALICE: SessionPrincipal = { kind: 'slack', workspace_id: 'T1', slack_user_id: 'user-alice' }
const BOB: SessionPrincipal = { kind: 'slack', workspace_id: 'T1', slack_user_id: 'user-bob' }
const CAROL: SessionPrincipal = { kind: 'slack', workspace_id: 'T1', slack_user_id: 'user-carol' }

function makeSession(opts: { state?: AgentSession['state']; pending?: PendingElevationRequest[] } = {}): AgentSession {
    return {
        id: '00000000-0000-4000-8000-00000000ee51',
        application_id: '00000000-0000-4000-8000-00000000aa01',
        revision_id: '00000000-0000-4000-8000-00000000ee52',
        team_id: 1,
        external_key: 'slack:C01:thread1',
        idempotency_key: null,
        trigger_metadata: null,
        state: opts.state ?? 'completed',
        conversation: [{ role: 'user', content: 'alice opened', timestamp: 1 }],
        pending_inputs: [],
        principal: ALICE,
        retry_count: 0,
        usage_total: { ...EMPTY_USAGE_TOTAL },
        acl: [],
        pending_elevation_requests: opts.pending ?? [],
        created_at: '2026-05-27',
        updated_at: '2026-05-27',
    }
}

function makePendingRequest(
    opts: { id?: string; requester?: SessionPrincipal; content?: string } = {}
): PendingElevationRequest {
    return {
        id: opts.id ?? 'req-1',
        requester: opts.requester ?? BOB,
        requester_display: 'slack:T01:U-BOB',
        trigger: 'slack',
        proposed_message: { role: 'user', content: opts.content ?? 'bob says hi', timestamp: 2 },
        created_at: '2026-05-27T00:00:00Z',
        state: 'pending',
    }
}

describe('authorizeGrant', () => {
    it('allows the session owner to grant a pending request', () => {
        const session = makeSession({ pending: [makePendingRequest()] })
        const result = authorizeGrant(session, 'req-1', ALICE)
        expect(result.ok).toBe(true)
    })

    it('rejects a non-owner with reason=not_session_owner', () => {
        const session = makeSession({ pending: [makePendingRequest()] })
        const result = authorizeGrant(session, 'req-1', CAROL)
        expect(result).toEqual({ ok: false, reason: 'not_session_owner' })
    })

    it('rejects an unknown request id', () => {
        const session = makeSession()
        const result = authorizeGrant(session, 'nope', ALICE)
        expect(result).toEqual({ ok: false, reason: 'request_not_found' })
    })

    it('rejects a request that has already been decided', () => {
        const decided = { ...makePendingRequest(), state: 'granted' as const, decision_at: 'now', decision_by: ALICE }
        const session = makeSession({ pending: [decided] })
        const result = authorizeGrant(session, 'req-1', ALICE)
        expect(result).toEqual({ ok: false, reason: 'request_not_pending' })
    })
})

describe('applyElevationGrant', () => {
    it('writes an ACL entry, marks request granted, replays the proposed message, queues the session', async () => {
        const queue = new PgSessionQueue(pool)
        const session = makeSession({ pending: [makePendingRequest({ content: 'bob says hi' })] })
        await queue.enqueue(session)

        const result = await applyElevationGrant(queue, session, { requestId: 'req-1', granter: ALICE })

        const after = await queue.get(session.id)
        expect(result.aclEntry.principal).toEqual(BOB)
        expect(result.aclEntry.granted_by).toEqual(ALICE)
        expect(after!.acl).toHaveLength(1)
        expect(after!.acl[0].state).toBe('active')
        expect(after!.pending_elevation_requests[0].state).toBe('granted')
        // The would-be message is replayed into pending_inputs so the runner
        // sees it on the next claim. Conversation is untouched.
        expect(after!.pending_inputs).toHaveLength(1)
        const replayed = after!.pending_inputs[0]
        expect(replayed.role).toBe('user')
        if (replayed.role === 'user') {
            expect(replayed.content).toBe('bob says hi')
        }
        expect(after!.state).toBe('queued')
    })

    it('honours an explicit expires_in_ms by stamping expires_at on the ACL entry', async () => {
        const queue = new PgSessionQueue(pool)
        const session = makeSession({ pending: [makePendingRequest()] })
        await queue.enqueue(session)

        const result = await applyElevationGrant(queue, session, {
            requestId: 'req-1',
            granter: ALICE,
            expiresInMs: 60_000,
        })
        expect(result.aclEntry.expires_at).toBeTruthy()
        expect(new Date(result.aclEntry.expires_at!).getTime()).toBeGreaterThan(Date.now())
    })

    it('a second grant on the same request is rejected from committed DB state, not the stale snapshot', async () => {
        // Replays the concurrent-double-apply scenario sequentially: both calls
        // hold the same in-memory `session` snapshot where the request is still
        // pending. The first commits the grant; the second must read the now
        // -granted DB state (under the row lock) and refuse — otherwise it would
        // append the proposed message into pending_inputs a second time.
        const queue = new PgSessionQueue(pool)
        const session = makeSession({ pending: [makePendingRequest({ content: 'bob says hi' })] })
        await queue.enqueue(session)

        await applyElevationGrant(queue, session, { requestId: 'req-1', granter: ALICE })
        await expect(applyElevationGrant(queue, session, { requestId: 'req-1', granter: ALICE })).rejects.toThrow(
            /not pending/
        )

        const after = await queue.get(session.id)
        expect(after!.acl).toHaveLength(1)
        expect(after!.pending_inputs).toHaveLength(1)
    })

    it('throws when applied to a non-pending request (idempotency stop)', async () => {
        const queue = new PgSessionQueue(pool)
        const decided = { ...makePendingRequest(), state: 'granted' as const, decision_at: 'now', decision_by: ALICE }
        const session = makeSession({ pending: [decided] })
        await queue.enqueue(session)
        await expect(applyElevationGrant(queue, session, { requestId: 'req-1', granter: ALICE })).rejects.toThrow(
            /not pending/
        )
    })

    it('throws when the request id is unknown', async () => {
        const queue = new PgSessionQueue(pool)
        const session = makeSession()
        await queue.enqueue(session)
        await expect(applyElevationGrant(queue, session, { requestId: 'missing', granter: ALICE })).rejects.toThrow(
            /not found/
        )
    })
})

describe('applyElevationDecline', () => {
    it('marks the request declined without mutating ACL or advancing the session', async () => {
        const queue = new PgSessionQueue(pool)
        const session = makeSession({ state: 'completed', pending: [makePendingRequest()] })
        await queue.enqueue(session)

        const declined = await applyElevationDecline(queue, session, { requestId: 'req-1', decider: ALICE })

        const after = await queue.get(session.id)
        expect(declined.state).toBe('declined')
        expect(declined.decision_by).toEqual(ALICE)
        expect(after!.acl).toHaveLength(0)
        expect(after!.pending_inputs).toHaveLength(0)
        // Session stays parked at completed (not advanced).
        expect(after!.state).toBe('completed')
        expect(after!.pending_elevation_requests[0].state).toBe('declined')
    })

    it('throws when the request is already decided', async () => {
        const queue = new PgSessionQueue(pool)
        const decided = { ...makePendingRequest(), state: 'declined' as const, decision_at: 'now', decision_by: ALICE }
        const session = makeSession({ pending: [decided] })
        await queue.enqueue(session)
        await expect(applyElevationDecline(queue, session, { requestId: 'req-1', decider: ALICE })).rejects.toThrow(
            /not pending/
        )
    })
})
