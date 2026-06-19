/**
 * Unit tests for the pure-logic branches inside `approval.ts`. The PG-backed
 * end-to-end behaviour (intercept → upsert → wake → dispatch) is covered by
 * `agent-tests/src/cases/approval-gated.test.ts`; this file pins the model-
 * facing envelope shape that varies on per-caller hints — currently the
 * posthog-code `client_kind` suppressing the URL + admin hint.
 */

import { describe, expect, it } from 'vitest'

import {
    AgentSession,
    ApprovalRequest,
    ApprovalStore,
    CLIENT_KIND_POSTHOG_CODE,
    EMPTY_USAGE_TOTAL,
    UpsertApprovalRequestInput,
    UpsertApprovalRequestResult,
} from '@posthog/agent-shared'

import { type ApprovalPolicy, queueApprovalResult } from './approval'

const TEST_SESSION_ID = '00000000-0000-4000-8000-00000000fe01'
const TEST_APP_ID = '00000000-0000-4000-8000-00000000fa01'
const TEST_REV_ID = '00000000-0000-4000-8000-00000000fb01'

function makeSession(over: Partial<AgentSession> = {}): AgentSession {
    return {
        id: TEST_SESSION_ID,
        application_id: TEST_APP_ID,
        revision_id: TEST_REV_ID,
        team_id: 1,
        external_key: null,
        idempotency_key: null,
        trigger_metadata: null,
        state: 'running',
        principal: null,
        conversation: [{ role: 'user', content: 'hi', timestamp: 0 }],
        pending_inputs: [],
        retry_count: 0,
        acl: [],
        pending_elevation_requests: [],
        usage_total: { ...EMPTY_USAGE_TOTAL },
        created_at: '2026-06-16',
        updated_at: '2026-06-16',
        ...over,
    }
}

/**
 * Minimal stub: queueApprovalResult only calls `upsertQueued` + `findLatestByArgs`
 * on the happy path. The PG-backed wire path is covered by approval-gated e2e.
 */
function makeStubStore(): ApprovalStore {
    return {
        async upsertQueued(input: UpsertApprovalRequestInput): Promise<UpsertApprovalRequestResult> {
            return {
                request: {
                    id: input.id,
                    session_id: input.session_id,
                    application_id: input.application_id,
                    revision_id: input.revision_id,
                    team_id: input.team_id,
                    turn: input.turn,
                    tool_call_id: input.tool_call_id,
                    tool_name: input.tool_name,
                    proposed_args: input.proposed_args,
                    args_hash: Buffer.alloc(0),
                    assistant_message: input.assistant_message,
                    approver_scope: input.approver_scope,
                    state: 'queued',
                    decision_by: null,
                    decision_at: null,
                    decision_reason: null,
                    decided_args: null,
                    dispatch_outcome: null,
                    expires_at: input.expires_at,
                    created_at: input.expires_at,
                } as ApprovalRequest,
                deduped: false,
            }
        },
        async findLatestByArgs(): Promise<ApprovalRequest | null> {
            return null
        },
    } as unknown as ApprovalStore
}

const POLICY: ApprovalPolicy = {
    approvers: ['team_admin'],
    allow_edit: false,
    allow_agent_approver: false,
    ttl_ms: 60_000,
}

function parseEnvelope(text: string): { approval: Record<string, unknown> } {
    return JSON.parse(text) as { approval: Record<string, unknown> }
}

describe('queueApprovalResult: model-facing envelope', () => {
    it('includes approver_hint + approval_url for the default (non-posthog-code) session', async () => {
        const store = makeStubStore()
        const out = await queueApprovalResult({
            approvals: store,
            buildApprovalUrl: (id) => `https://console.example.com/approvals?request=${id}`,
            session: makeSession(),
            revisionId: TEST_REV_ID,
            turn: 1,
            toolName: '@posthog/memory-write',
            toolCallId: 'tc-1',
            args: { note: 'apples' },
            policy: POLICY,
        })
        const envelope = parseEnvelope((out.content[0] as { text: string }).text)
        expect(envelope.approval).toMatchObject({
            state: 'queued',
            approver_hint: expect.stringMatching(/admin/i),
            approval_url: expect.stringContaining('https://console.example.com/approvals?request='),
        })
    })

    it('omits approver_hint + approval_url when the session was opened by posthog-code', async () => {
        const store = makeStubStore()
        const out = await queueApprovalResult({
            approvals: store,
            buildApprovalUrl: (id) => `https://console.example.com/approvals?request=${id}`,
            session: makeSession({ trigger_metadata: { kind: 'chat', client_kind: CLIENT_KIND_POSTHOG_CODE } }),
            revisionId: TEST_REV_ID,
            turn: 1,
            toolName: '@posthog/memory-write',
            toolCallId: 'tc-1',
            args: { note: 'apples' },
            policy: POLICY,
        })
        const envelope = parseEnvelope((out.content[0] as { text: string }).text)
        // Posthog-code's chat preview renders an in-line approval card — the
        // model has nothing to repeat about how the user should approve, so
        // the URL + admin hint must not appear in the envelope it sees.
        expect(envelope.approval.approver_hint).toBeUndefined()
        expect(envelope.approval.approval_url).toBeUndefined()
        // Still has the bits the model uses to know it's gated.
        expect(envelope.approval).toMatchObject({ state: 'queued', request_id: expect.any(String) })
    })

    it('treats an unrecognised client_kind as the default (URL + hint preserved)', async () => {
        const store = makeStubStore()
        const out = await queueApprovalResult({
            approvals: store,
            buildApprovalUrl: (id) => `https://console.example.com/approvals?request=${id}`,
            session: makeSession({ trigger_metadata: { kind: 'chat', client_kind: 'some-future-client' } }),
            revisionId: TEST_REV_ID,
            turn: 1,
            toolName: '@posthog/memory-write',
            toolCallId: 'tc-1',
            args: { note: 'apples' },
            policy: POLICY,
        })
        const envelope = parseEnvelope((out.content[0] as { text: string }).text)
        expect(envelope.approval.approver_hint).not.toBeUndefined()
        expect(envelope.approval.approval_url).not.toBeUndefined()
    })
})
