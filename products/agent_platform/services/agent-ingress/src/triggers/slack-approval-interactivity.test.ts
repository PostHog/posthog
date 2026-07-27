/**
 * Slack approval-button interactivity: decision routing + feedback.
 *
 * Covers the two behaviours that broke when feedback was sent in the synchronous
 * HTTP body (Slack ignores it for Block Kit `block_actions`):
 *   - the decided-state message replacement on a principal's approve/reject,
 *   - the "not yours" ephemeral when a non-principal clicks,
 * both now delivered via the interaction's `response_url`.
 *
 * Also pins the tenant/session-binding fix: the session is derived from the
 * approval ROW, not the attacker-influenceable action-value `sessionId`.
 */

import { describe, expect, it } from 'vitest'

import type {
    AgentSession,
    ApprovalRequest,
    ApprovalStore,
    SessionPrincipal,
    SessionQueue,
} from '@posthog/agent-shared'

import { handleApprovalDecisionAction } from './slack'
import type { RouteCtx } from './types'

const APP_ID = 'app-1'
const ROW_SESSION = 'sess-row'
const OWNER: SessionPrincipal = { kind: 'slack', workspace_id: 'W1', slack_user_id: 'U-owner' }

function fakeRow(over: Partial<ApprovalRequest> = {}): ApprovalRequest {
    return {
        id: 'req-1',
        session_id: ROW_SESSION,
        application_id: APP_ID,
        team_id: 1,
        revision_id: 'rev-1',
        turn: 1,
        tool_call_id: 'tc-1',
        tool_name: '@posthog/team-delete',
        proposed_args: {},
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

interface HttpCall {
    url: string
    body: Record<string, unknown>
}

interface Harness {
    ctx: RouteCtx
    calls: {
        markApproving: number
        markRejected: number
        sessionLookups: string[]
        http: HttpCall[]
        ack: unknown[]
    }
}

function harness(opts: {
    row?: ApprovalRequest | null
    /** Principal stamped on the session the ROW points at. */
    sessionPrincipal?: SessionPrincipal
    /** Slack user id of the button clicker. */
    clickerUserId?: string
}): Harness {
    const row = opts.row === undefined ? fakeRow() : opts.row
    const calls = {
        markApproving: 0,
        markRejected: 0,
        sessionLookups: [] as string[],
        http: [] as HttpCall[],
        ack: [] as unknown[],
    }

    const approvals = {
        getForApplication: async (id: string, applicationId: string) =>
            row && row.id === id && row.application_id === applicationId ? row : null,
        markApproving: async (id: string) => {
            calls.markApproving++
            return fakeRow({ id, state: 'approving' })
        },
        markRejected: async (id: string) => {
            calls.markRejected++
            return fakeRow({ id, state: 'rejected' })
        },
    } as unknown as ApprovalStore

    const queue = {
        // getOwnedSession routes through this; only the ROW's session resolves.
        getForApplication: async (sessionId: string, applicationId: string) => {
            calls.sessionLookups.push(sessionId)
            if (sessionId !== ROW_SESSION || applicationId !== APP_ID) {
                return null
            }
            return {
                id: ROW_SESSION,
                team_id: 1,
                application_id: APP_ID,
                principal: opts.sessionPrincipal ?? OWNER,
            } as unknown as AgentSession
        },
        appendPendingInput: async () => undefined,
        update: async () => undefined,
    } as unknown as SessionQueue

    const http = {
        fetch: async (url: string, init?: { body?: string }) => {
            calls.http.push({ url, body: init?.body ? JSON.parse(init.body) : {} })
            return { ok: true } as Response
        },
    }

    const res = {
        status: () => res,
        json: (payload: unknown) => {
            calls.ack.push(payload)
            return res
        },
    }

    const ctx = {
        req: {},
        res,
        deps: { approvals, queue, http },
        resolved: { application: { id: APP_ID } },
    } as unknown as RouteCtx

    return { ctx, calls }
}

const payload = (clickerUserId: string): { team: { id: string }; user: { id: string }; response_url: string } => ({
    team: { id: 'W1' },
    user: { id: clickerUserId },
    response_url: 'https://hooks.slack.test/r/abc',
})

describe('handleApprovalDecisionAction', () => {
    it('approve by the session principal: applies the decision and replaces the message via response_url', async () => {
        const { ctx, calls } = harness({ sessionPrincipal: OWNER })
        // Decoy sessionId in the action value differs from the row's session.
        await handleApprovalDecisionAction(ctx, payload('U-owner') as never, {
            sessionId: 'sess-DECOY',
            requestId: 'req-1',
            decision: 'approve',
        })

        expect(calls.markApproving).toBe(1)
        // Fix: the session is looked up by the ROW's session, never the decoy.
        expect(calls.sessionLookups).toEqual([ROW_SESSION])
        // Feedback goes to response_url (not the synchronous body), replacing
        // the buttons with the decided state.
        expect(calls.http).toHaveLength(1)
        expect(calls.http[0].url).toBe('https://hooks.slack.test/r/abc')
        expect(calls.http[0].body).toMatchObject({ replace_original: true, text: '✓ Approved.' })
        // The HTTP response is a bare ack.
        expect(calls.ack).toEqual([{ ok: true }])
    })

    it('reject by the principal: replaces the message with the rejected state', async () => {
        const { ctx, calls } = harness({ sessionPrincipal: OWNER })
        await handleApprovalDecisionAction(ctx, payload('U-owner') as never, {
            sessionId: ROW_SESSION,
            requestId: 'req-1',
            decision: 'reject',
        })
        expect(calls.markRejected).toBe(1)
        expect(calls.http[0].body).toMatchObject({ replace_original: true, text: '✗ Rejected.' })
    })

    it('a non-principal clicker is refused with an ephemeral via response_url and no decision', async () => {
        const { ctx, calls } = harness({ sessionPrincipal: OWNER })
        await handleApprovalDecisionAction(ctx, payload('U-intruder') as never, {
            sessionId: ROW_SESSION,
            requestId: 'req-1',
            decision: 'approve',
        })
        expect(calls.markApproving).toBe(0)
        expect(calls.http).toHaveLength(1)
        expect(calls.http[0].body).toMatchObject({ response_type: 'ephemeral', replace_original: false })
        expect(String(calls.http[0].body.text)).toContain('Only the person who started this session')
    })

    it('an agent-type row is not decidable here (console-only): not-found ephemeral, no decision', async () => {
        const { ctx, calls } = harness({
            row: fakeRow({ approver_scope: { type: 'agent', allow_edit: false } }),
            sessionPrincipal: OWNER,
        })
        await handleApprovalDecisionAction(ctx, payload('U-owner') as never, {
            sessionId: ROW_SESSION,
            requestId: 'req-1',
            decision: 'approve',
        })
        expect(calls.markApproving).toBe(0)
        expect(calls.sessionLookups).toEqual([]) // never reaches the session lookup
        expect(calls.http[0].body).toMatchObject({ response_type: 'ephemeral' })
        expect(String(calls.http[0].body.text)).toContain('could not be found')
    })

    it('a legacy `team_admins` row (no `type`) is treated as agent-type and refused here', async () => {
        const { ctx, calls } = harness({
            // Pre-rebuild shape: `approvers` instead of `type`. Must still gate to
            // the console, not be decidable as a principal request.
            row: fakeRow({ approver_scope: { approvers: ['team_admins'] } as never }),
            sessionPrincipal: OWNER,
        })
        await handleApprovalDecisionAction(ctx, payload('U-owner') as never, {
            sessionId: ROW_SESSION,
            requestId: 'req-1',
            decision: 'approve',
        })
        expect(calls.markApproving).toBe(0)
        expect(calls.http[0].body).toMatchObject({ response_type: 'ephemeral' })
    })

    it('a missing row collapses to a not-found ephemeral', async () => {
        const { ctx, calls } = harness({ row: null })
        await handleApprovalDecisionAction(ctx, payload('U-owner') as never, {
            sessionId: ROW_SESSION,
            requestId: 'missing',
            decision: 'approve',
        })
        expect(calls.markApproving).toBe(0)
        expect(calls.http[0].body).toMatchObject({ response_type: 'ephemeral' })
    })
})
