/**
 * Sample approval-gated tool calls for stories and mocked console reads.
 *
 * Shape mirrors the Django `AgentApprovalRequestApi` field set (see
 * `products/agent_platform/services/agent-console/src/generated/
 * agent-platform.api.schemas.ts`) so stories exercise the same apiClient
 * mappers as production. Each fixture's `session_id` points at a real
 * session fixture so the approval detail's Session tab renders the
 * conversation that proposed the call.
 */

import { incidentTriager, releaseConcierge, weeklyDigest } from './agents'

export type ApprovalStateFixture =
    | 'queued'
    | 'approving'
    | 'dispatched'
    | 'dispatched_failed'
    | 'rejected'
    | 'expired'

export interface AgentApprovalRequestFixture {
    id: string
    session_id: string
    application_id: string
    team_id: number
    revision_id: string
    turn: number
    tool_call_id: string
    tool_name: string
    proposed_args: Record<string, unknown>
    decided_args: Record<string, unknown> | null
    assistant_message: Record<string, unknown>
    approver_scope: Record<string, unknown>
    state: ApprovalStateFixture
    decision_by: string | null
    decision_at: string | null
    decision_reason: string | null
    dispatch_outcome: Record<string, unknown> | null
    created_at: string
    expires_at: string
}

/** Queued, editable — the agent wants to open a hotfix PR. Backs the Slack-triggered release session. */
export const queuedPrApproval: AgentApprovalRequestFixture = {
    id: '01998a01-3333-7000-8000-000000000001',
    session_id: '01998a01-2222-7000-8000-000000000102', // releaseAwaitingSession
    application_id: releaseConcierge.id,
    team_id: 2,
    revision_id: releaseConcierge.live_revision!,
    turn: 1,
    tool_call_id: 'fleet-call-1',
    tool_name: 'github.pull_request_open',
    proposed_args: { repo: 'posthog/posthog', base: 'release/2.40', head: 'hotfix/tz-2.40' },
    decided_args: null,
    assistant_message: {
        role: 'assistant',
        content: [
            {
                type: 'thinking',
                thinking: 'The timezone fix is isolated to one module and has a test. Opening against the release branch is the right move, but pushing to a protected branch is gated — surfacing for approval.',
            },
            {
                type: 'text',
                text: 'Patch is ready. Opening a PR against `release/2.40` — needs your approval to push.',
            },
        ],
    },
    approver_scope: { approvers: ['session_owner'], allow_edit: true, allow_agent_approver: false },
    state: 'queued',
    decision_by: null,
    decision_at: null,
    decision_reason: null,
    dispatch_outcome: null,
    created_at: '2026-05-28T15:38:30Z',
    expires_at: '2026-05-29T15:38:30Z',
}

/** Queued, NOT editable — a destructive call the spec dispatches verbatim. */
export const queuedTeamDeleteApproval: AgentApprovalRequestFixture = {
    id: '01998a01-3333-7000-8000-000000000002',
    session_id: '01998a01-2222-7000-8000-000000000103', // triagerStreamingSession
    application_id: incidentTriager.id,
    team_id: 2,
    revision_id: incidentTriager.live_revision!,
    turn: 2,
    tool_call_id: 'triage-call-7',
    tool_name: '@posthog/feature-flag-disable',
    proposed_args: { flag_key: 'new-ingest-path', reason: 'p99 regression in prod-eu' },
    decided_args: null,
    assistant_message: {
        role: 'assistant',
        content: [
            {
                type: 'text',
                text: 'The new ingest path correlates with the p99 spike. I recommend disabling the `new-ingest-path` flag to roll back. This is gated — approve to apply.',
            },
        ],
    },
    approver_scope: { approvers: ['oncall'], allow_edit: false, allow_agent_approver: false },
    state: 'queued',
    decision_by: null,
    decision_at: null,
    decision_reason: null,
    dispatch_outcome: null,
    created_at: '2026-05-28T15:53:10Z',
    expires_at: '2026-05-28T17:53:10Z',
}

/** Approved + dispatched successfully, with approver edits applied. */
export const dispatchedApproval: AgentApprovalRequestFixture = {
    id: '01998a01-3333-7000-8000-000000000003',
    session_id: '01998a01-2222-7000-8000-000000000101', // releaseStreamingSession
    application_id: releaseConcierge.id,
    team_id: 2,
    revision_id: releaseConcierge.live_revision!,
    turn: 3,
    tool_call_id: 'fleet-call-9',
    tool_name: 'github.pull_request_merge',
    proposed_args: { repo: 'posthog/posthog', pull_number: 41201, merge_method: 'squash' },
    decided_args: { repo: 'posthog/posthog', pull_number: 41201, merge_method: 'rebase' },
    assistant_message: {
        role: 'assistant',
        content: [{ type: 'text', text: 'Checks are green. Ready to merge the v2.41 changelog PR.' }],
    },
    approver_scope: { approvers: ['session_owner'], allow_edit: true, allow_agent_approver: false },
    state: 'dispatched',
    decision_by: '01998a01-9999-7000-8000-0000000000a1',
    decision_at: '2026-05-28T15:48:02Z',
    decision_reason: 'Prefer rebase to keep release history linear.',
    dispatch_outcome: { result: { merged: true, sha: 'd34db33fc0ffee1234567890abcdef0987654321' } },
    created_at: '2026-05-28T15:47:30Z',
    expires_at: '2026-05-28T17:47:30Z',
}

/** Approver said no. */
export const rejectedApproval: AgentApprovalRequestFixture = {
    id: '01998a01-3333-7000-8000-000000000004',
    session_id: '01998a01-2222-7000-8000-0000000007d2', // weeklyDigest chat test run
    application_id: weeklyDigest.id,
    team_id: 2,
    revision_id: weeklyDigest.live_revision!,
    turn: 4,
    tool_call_id: 'digest-call-3',
    tool_name: '@posthog/slack-post-message',
    proposed_args: { channel: '#product-eng', text: 'Draft digest — please review before Monday.' },
    decided_args: null,
    assistant_message: {
        role: 'assistant',
        content: [{ type: 'text', text: 'Digest draft is ready. Posting to #product-eng for review.' }],
    },
    approver_scope: { approvers: ['session_owner'], allow_edit: true, allow_agent_approver: false },
    state: 'rejected',
    decision_by: '01998a01-9999-7000-8000-0000000000a1',
    decision_at: '2026-05-28T16:02:11Z',
    decision_reason: 'This is a test run — don’t post to the real channel.',
    dispatch_outcome: null,
    created_at: '2026-05-28T16:01:40Z',
    expires_at: '2026-05-28T18:01:40Z',
}

/** Approved, but the tool threw when it ran. */
export const dispatchedFailedApproval: AgentApprovalRequestFixture = {
    id: '01998a01-3333-7000-8000-000000000005',
    session_id: '01998a01-2222-7000-8000-0000000007d3', // weeklyDigest failed run
    application_id: weeklyDigest.id,
    team_id: 2,
    revision_id: weeklyDigest.live_revision!,
    turn: 2,
    tool_call_id: 'digest-call-8',
    tool_name: 'github.pull_request_open',
    proposed_args: { repo: 'posthog/posthog', base: 'master', head: 'digest/skill-tweak' },
    decided_args: null,
    assistant_message: {
        role: 'assistant',
        content: [{ type: 'text', text: 'Opening a PR with the updated digest skill.' }],
    },
    approver_scope: { approvers: ['session_owner'], allow_edit: true, allow_agent_approver: false },
    state: 'dispatched_failed',
    decision_by: '01998a01-9999-7000-8000-0000000000a1',
    decision_at: '2026-05-28T16:20:05Z',
    decision_reason: null,
    dispatch_outcome: { error: 'GitHub API 422: head branch `digest/skill-tweak` does not exist.' },
    created_at: '2026-05-28T16:19:50Z',
    expires_at: '2026-05-28T18:19:50Z',
}

/** All approvals across the fleet, newest first. */
export const fleetApprovals: AgentApprovalRequestFixture[] = [
    queuedTeamDeleteApproval,
    dispatchedFailedApproval,
    rejectedApproval,
    dispatchedApproval,
    queuedPrApproval,
]

export function listApprovalsForAgentFixture(applicationId: string): AgentApprovalRequestFixture[] {
    return fleetApprovals.filter((a) => a.application_id === applicationId)
}

export function getApprovalFixture(id: string): AgentApprovalRequestFixture | null {
    return fleetApprovals.find((a) => a.id === id) ?? null
}
