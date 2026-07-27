import { describe, expect, it } from 'vitest'

import type { ConversationMessage } from '../spec/spec'
import { applyApprovalDecision, buildApprovalDecidedMarker, parseApprovalDecidedMarker } from './approval-decision'
import type { ApprovalRequest, ApprovalStore, DecideApprovalInput } from './approval-store'
import type { SessionQueue } from './queue'

function fakeRow(over: Partial<ApprovalRequest> = {}): ApprovalRequest {
    return {
        id: 'req-1',
        session_id: 'sess-1',
        application_id: 'app-1',
        team_id: 1,
        revision_id: 'rev-1',
        turn: 1,
        tool_call_id: 'tc-1',
        tool_name: '@posthog/team-delete',
        proposed_args: { team_id: 42 },
        args_hash: Buffer.from(''),
        assistant_message: { role: 'assistant', content: [{ type: 'text', text: '' }], timestamp: 0 },
        approver_scope: { type: 'principal', allow_edit: false },
        state: 'queued',
        decision_by: null,
        decision_at: null,
        decision_reason: null,
        decided_args: null,
        dispatch_outcome: null,
        created_at: '2026-01-01T00:00:00Z',
        expires_at: '2026-01-02T00:00:00Z',
        ...over,
    }
}

interface Harness {
    approvals: ApprovalStore
    queue: SessionQueue
    calls: {
        markApproving: DecideApprovalInput[]
        markRejected: DecideApprovalInput[]
        appended: { sessionId: string; msg: ConversationMessage }[]
        updated: { sessionId: string; patch: unknown }[]
    }
}

/** Minimal ApprovalStore + SessionQueue doubles recording the calls we assert. */
function harness(opts: { row: ApprovalRequest | null; markReturnsNull?: boolean }): Harness {
    const calls = {
        markApproving: [] as DecideApprovalInput[],
        markRejected: [] as DecideApprovalInput[],
        appended: [] as { sessionId: string; msg: ConversationMessage }[],
        updated: [] as { sessionId: string; patch: unknown }[],
    }
    const approvals = {
        get: async () => opts.row,
        getForApplication: async (id: string, applicationId: string) =>
            opts.row && opts.row.id === id && opts.row.application_id === applicationId ? opts.row : null,
        markApproving: async (id: string, input: DecideApprovalInput) => {
            calls.markApproving.push(input)
            return opts.markReturnsNull
                ? null
                : fakeRow({ ...opts.row!, id, state: 'approving', decision_by: input.decided_by })
        },
        markRejected: async (id: string, input: DecideApprovalInput) => {
            calls.markRejected.push(input)
            return opts.markReturnsNull
                ? null
                : fakeRow({
                      ...opts.row!,
                      id,
                      state: 'rejected',
                      decision_by: input.decided_by,
                      decision_reason: input.reason ?? null,
                  })
        },
    } as unknown as ApprovalStore
    const queue = {
        appendPendingInput: async (sessionId: string, msg: ConversationMessage) => {
            calls.appended.push({ sessionId, msg })
        },
        update: async (sessionId: string, patch: unknown) => {
            calls.updated.push({ sessionId, patch })
        },
    } as unknown as SessionQueue
    return { approvals, queue, calls }
}

describe('applyApprovalDecision', () => {
    it('approve: marks approving, appends the decided marker, wakes the session', async () => {
        const h = harness({ row: fakeRow() })
        const result = await applyApprovalDecision(h, {
            requestId: 'req-1',
            applicationId: 'app-1',
            decision: 'approve',
            decidedBy: 'user-9',
        })
        expect(result).toEqual({ ok: true, state: 'approving' })
        expect(h.calls.markApproving[0].decided_by).toBe('user-9')
        // The wake is the decided marker (the runner picks it up next turn).
        const text = (h.calls.appended[0].msg.content as { text: string }[])[0].text
        expect(parseApprovalDecidedMarker(text)).toBe('req-1')
        expect(h.calls.updated[0].patch).toEqual({ state: 'queued' })
    })

    it('reject: marks rejected and materialises a rejection envelope (not a marker)', async () => {
        const h = harness({ row: fakeRow() })
        const result = await applyApprovalDecision(h, {
            requestId: 'req-1',
            applicationId: 'app-1',
            decision: 'reject',
            decidedBy: 'user-9',
            reason: 'nope',
        })
        expect(result).toEqual({ ok: true, state: 'rejected' })
        const text = (h.calls.appended[0].msg.content as { text: string }[])[0].text
        expect(parseApprovalDecidedMarker(text)).toBeNull()
        expect(JSON.parse(text).approval).toMatchObject({ request_id: 'req-1', state: 'rejected', reason: 'nope' })
        expect(h.calls.updated[0].patch).toEqual({ state: 'queued' })
    })

    it('returns not_found when the row is missing', async () => {
        const h = harness({ row: null })
        expect(await applyApprovalDecision(h, { requestId: 'x', decision: 'approve', decidedBy: 'u' })).toEqual({
            ok: false,
            error: 'not_found',
        })
    })

    it('returns not_queued for an already-decided row', async () => {
        const h = harness({ row: fakeRow({ state: 'approving' }) })
        expect(
            await applyApprovalDecision(h, {
                requestId: 'req-1',
                applicationId: 'app-1',
                decision: 'approve',
                decidedBy: 'u',
            })
        ).toEqual({ ok: false, error: 'not_queued', state: 'approving' })
    })

    it('rejects edits when the policy did not allow_edit', async () => {
        const h = harness({ row: fakeRow({ approver_scope: { type: 'principal', allow_edit: false } }) })
        const result = await applyApprovalDecision(h, {
            requestId: 'req-1',
            applicationId: 'app-1',
            decision: 'approve',
            decidedBy: 'u',
            editedArgs: { team_id: 7 },
        })
        expect(result).toEqual({ ok: false, error: 'edits_not_allowed' })
        expect(h.calls.markApproving).toHaveLength(0)
    })

    it('returns race_lost when the atomic flip loses to a concurrent decider', async () => {
        const h = harness({ row: fakeRow(), markReturnsNull: true })
        expect(
            await applyApprovalDecision(h, {
                requestId: 'req-1',
                applicationId: 'app-1',
                decision: 'approve',
                decidedBy: 'u',
            })
        ).toEqual({ ok: false, error: 'race_lost' })
    })

    it('marker round-trips', () => {
        expect(parseApprovalDecidedMarker(buildApprovalDecidedMarker('abc'))).toBe('abc')
        expect(parseApprovalDecidedMarker('not-a-marker')).toBeNull()
    })
})
