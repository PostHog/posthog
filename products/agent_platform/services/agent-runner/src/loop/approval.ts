/**
 * Approval-gated tool helpers for the driver.
 *
 * Two halves of the loop:
 *
 *   - `queueApprovalResult` is what a gated tool's `execute` runs instead of
 *     the real tool: it upserts an `agent_tool_approval_request` row and
 *     returns a synthetic *queued* tool result (the approval envelope as
 *     JSON text, `isError: false`, `terminate: false`) so the session keeps
 *     going without parking.
 *   - `dispatchApprovedResult` runs on resume when a decided marker lands in
 *     `pending_inputs`: it executes the real tool (via the adapter's real
 *     `execute`, bypassing the gate the human already cleared), finalises the
 *     row, and returns a *wake* `user` message carrying the approved envelope.
 *     It returns the message rather than pushing it so the driver can hand it
 *     to the loop as a steering message (the loop appends it via `message_end`).
 *
 * Both kept free of bus/analytics emission — the driver owns those off the
 * loop's event stream — so these stay pure row+envelope logic.
 */

import type { AgentToolResult } from '@earendil-works/pi-agent-core'
import { randomUUID } from 'node:crypto'

import {
    AgentSession,
    ApprovalRequest,
    ApprovalStore,
    type ApprovalType,
    AssistantMessageRecord,
    ConversationMessage,
    hashCanonicalArgs,
    parseApprovalDecidedMarker,
} from '@posthog/agent-shared'

import type { RealToolExecute, ToolResultDetails } from './build-agent-tools'

// Who the model should tell the user to expect a decision from, by approval type.
const APPROVER_HINT_PRINCIPAL = 'you — the person who started this session'
const APPROVER_HINT_AGENT = 'an owner or admin of this agent'

/** `ToolRef.approval_policy` after Zod parsing. */
export interface ApprovalPolicy {
    type: ApprovalType
    allow_edit: boolean
    ttl_ms: number
}

/** Returns the approval request id when `msg` is the janitor's wake marker. */
export function approvalMarkerRequestId(msg: ConversationMessage): string | null {
    if (msg.role !== 'user') {
        return null
    }
    if (typeof msg.content === 'string') {
        return parseApprovalDecidedMarker(msg.content)
    }
    if (Array.isArray(msg.content) && msg.content.length === 1 && msg.content[0].type === 'text') {
        return parseApprovalDecidedMarker(msg.content[0].text)
    }
    return null
}

/**
 * Gated-tool `execute`: upsert the queued row, return the synthetic queued
 * result. `terminate` is false — the model reads the envelope and continues.
 *
 * Capped at `maxOpenApprovals` open (queued) rows per session
 * (`spec.limits.max_open_approvals`): a model looping on a gated tool with
 * distinct args would otherwise flood approvers — args-hash dedupe only
 * collapses identical calls. An identical re-ask dedupes onto its existing
 * queued row and is always allowed; only a call that would insert a NEW row
 * counts against the cap. At the cap the model receives a synthetic
 * `approval_budget_exhausted` error (no row written, no approver ping) and
 * continues the turn.
 */
export async function queueApprovalResult(input: {
    approvals: ApprovalStore
    buildApprovalUrl?: (requestId: string) => string
    session: AgentSession
    revisionId: string
    turn: number
    toolName: string
    toolCallId: string
    args: Record<string, unknown>
    policy: ApprovalPolicy
    maxOpenApprovals: number
}): Promise<AgentToolResult<ToolResultDetails>> {
    const argsHash = hashCanonicalArgs(input.args)
    const previous = await input.approvals.findLatestByArgs(input.session.id, input.toolName, argsHash)
    const lastAssistant = findLastAssistant(input.session.conversation)

    // An identical re-ask (existing `queued` row) is exempt from the cap: it
    // dedupes onto that row via the partial unique index without growing the
    // approver queue, so blocking it would spuriously reject a legitimate
    // retry. Keep the dedupe exemption ahead of the cap check — reordering
    // them so the cap runs first breaks that. The exemption opens a bounded
    // TOCTOU: if an approver decides the queued row between `findLatestByArgs`
    // and `upsertQueued`, the insert no longer conflicts and a new row lands
    // uncapped (cap+1). It's self-correcting — that same decision freed a slot
    // — so overshoot is bounded at 1 per concurrent decision.
    if (previous?.state !== 'queued') {
        const open = await input.approvals.countQueuedBySession(input.session.id)
        if (open >= input.maxOpenApprovals) {
            // Same policy-aware phrasing as the queued path's `approver_hint`:
            // `agent` policies are decided by an owner/admin, not the session user.
            const approverHint = input.policy.type === 'agent' ? APPROVER_HINT_AGENT : APPROVER_HINT_PRINCIPAL
            return {
                content: [
                    {
                        type: 'text',
                        text: JSON.stringify({
                            error: {
                                code: 'approval_budget_exhausted',
                                message:
                                    `this session already has ${open} approval request(s) awaiting a decision ` +
                                    `(limit ${input.maxOpenApprovals}). The call was NOT queued. Do not re-issue ` +
                                    `gated calls; the pending requests must be decided by ${approverHint} first.`,
                            },
                        }),
                    },
                ],
                details: {},
                terminate: false,
            }
        }
    }

    const upsert = await input.approvals.upsertQueued({
        id: randomUUID(),
        session_id: input.session.id,
        application_id: input.session.application_id,
        team_id: input.session.team_id,
        revision_id: input.revisionId,
        turn: input.turn,
        tool_call_id: input.toolCallId,
        tool_name: input.toolName,
        proposed_args: input.args,
        assistant_message: lastAssistant ?? {
            role: 'assistant',
            content: [{ type: 'text', text: '' }],
            timestamp: Date.now(),
        },
        approver_scope: {
            type: input.policy.type,
            allow_edit: input.policy.allow_edit,
        },
        expires_at: new Date(Date.now() + input.policy.ttl_ms).toISOString(),
    })

    const buildUrl = input.buildApprovalUrl ?? defaultApprovalUrl
    const approval: Record<string, unknown> = {
        request_id: upsert.request.id,
        state: 'queued',
        // The inline approval card renders straight from this envelope (live
        // `tool_result` + persisted transcript on reload) — no extra fetch. It
        // needs the edit affordance and whether it's decidable inline
        // (`principal`) or console-only (`agent`); neither is on the tool_call.
        allow_edit: input.policy.allow_edit,
        approver_scope: { type: input.policy.type },
        approver_hint: input.policy.type === 'agent' ? APPROVER_HINT_AGENT : APPROVER_HINT_PRINCIPAL,
        approval_url: buildUrl(upsert.request.id),
    }
    if (!upsert.deduped && previous && isTerminal(previous.state)) {
        approval.prior_decision = { state: previous.state, reason: previous.decision_reason ?? undefined }
    }

    return {
        content: [{ type: 'text', text: JSON.stringify({ approval }) }],
        details: {
            queued: true,
            requestId: upsert.request.id,
            deduped: upsert.deduped,
            allowEdit: input.policy.allow_edit,
            approverType: input.policy.type,
        },
        terminate: false,
    }
}

export interface ApprovedDispatch {
    /** The wake message to inject as steering — a `user` message, not a tool result. */
    wake: ConversationMessage
    isError: boolean
    /** Raw tool output on success, for the analytics span. */
    output: unknown
    error?: string
    requestId: string
    toolName: string
    toolCallId: string
    args: Record<string, unknown>
}

/**
 * Run a previously-approved call through the tool's real `execute`, finalise
 * the row, and build the wake message. Bypasses the gate intentionally.
 *
 * The wake is a `user` message (not a tool result): by approval time the prior
 * assistant message no longer carries the matching tool_use, and strict
 * providers reject an orphaned tool_result for the same id. The queued
 * synthetic tool_result already paired with the tool_use at call time.
 */
export async function dispatchApprovedResult(input: {
    approvals: ApprovalStore
    realExecute: RealToolExecute | undefined
    row: ApprovalRequest
}): Promise<ApprovedDispatch> {
    const { row } = input
    const args = (row.decided_args ?? row.proposed_args) as Record<string, unknown>

    let isError = false
    let output: unknown
    let error: string | undefined
    if (!input.realExecute) {
        isError = true
        error = `native tool unknown: ${row.tool_name}`
    } else {
        try {
            const result = await input.realExecute(row.tool_call_id, args)
            output = (result.details as ToolResultDetails | undefined)?.output
        } catch (err) {
            isError = true
            error = (err as Error).message
        }
    }

    await input.approvals.markDispatched(row.id, isError ? { error } : { result: output })

    const envelope: Record<string, unknown> = {
        approval: {
            request_id: row.id,
            state: 'approved',
            decided_by: row.decision_by ?? undefined,
            edited_args: row.decided_args !== null,
        },
    }
    if (isError) {
        envelope.error = error
    } else {
        envelope.result = output
    }

    const wake: ConversationMessage = {
        role: 'user',
        content: [{ type: 'text', text: JSON.stringify(envelope) }],
        timestamp: Date.now(),
    }
    return {
        wake,
        isError,
        output,
        error,
        requestId: row.id,
        toolName: row.tool_name,
        toolCallId: row.tool_call_id,
        args,
    }
}

function isTerminal(state: ApprovalRequest['state']): boolean {
    return state === 'rejected' || state === 'expired' || state === 'dispatched_failed' || state === 'dispatched'
}

function findLastAssistant(conv: ConversationMessage[]): AssistantMessageRecord | null {
    for (let i = conv.length - 1; i >= 0; i--) {
        const m = conv[i]
        if (m.role === 'assistant') {
            return m
        }
    }
    return null
}

// Fallback when the runner didn't wire `buildApprovalUrl` (e.g. tests). Mirrors
// the prod scheme so the unwired path stays usable instead of cryptic; index.ts
// wires the dev/prod scheme via config.approvalLinkScheme.
function defaultApprovalUrl(requestId: string): string {
    return `posthog-code://approval/${requestId}`
}
