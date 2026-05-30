import { DangerousOperationResponse, PENDING_APPROVAL_STATUS } from '~/queries/schema/schema-assistant-messages'
import { PendingApproval } from '~/types'

import { PermissionOption, PermissionRequestRecord } from './types/sandboxStreamTypes'

/**
 * Type guard to check if a tool result is a dangerous operation requiring approval.
 * Validates all required fields are present (supports both camelCase and snake_case from backend).
 */
export function isDangerousOperationResponse(result: unknown): result is DangerousOperationResponse {
    if (typeof result !== 'object' || result === null) {
        return false
    }
    const r = result as Record<string, unknown>
    return (
        r.status === PENDING_APPROVAL_STATUS &&
        (typeof r.proposalId === 'string' || typeof r.proposal_id === 'string') &&
        (typeof r.toolName === 'string' || typeof r.tool_name === 'string') &&
        typeof r.preview === 'string' &&
        typeof r.payload === 'object' &&
        r.payload !== null
    )
}

type DangerousOperationResponseLike = {
    status?: string
    proposalId?: string
    proposal_id?: string
    toolName?: string
    tool_name?: string
    preview?: string
    payload?: Record<string, unknown>
}

export function normalizeDangerousOperationResponse(
    result: DangerousOperationResponseLike | DangerousOperationResponse
): DangerousOperationResponse {
    // Fallback values are defensive
    const r = result as DangerousOperationResponseLike
    return {
        status: PENDING_APPROVAL_STATUS,
        proposalId: r.proposalId ?? r.proposal_id ?? '',
        toolName: r.toolName ?? r.tool_name ?? '',
        preview: r.preview ?? '',
        payload: r.payload ?? {},
    }
}

/**
 * Map a sandbox-runtime ACP `PermissionRequestRecord` onto the existing `PendingApproval` shape so
 * the unchanged `DangerousOperationApprovalCard` can render it. The card resolves on `proposal_id`,
 * so we key on `requestId`; `original_tool_call_id` carries the ACP `toolCallId` so `Thread.tsx` can
 * place the card next to the originating tool call. The ACP `options[]` ride inside `payload.options`
 * — the option-kind -> affordance mapping + sandbox card variant land in UI-C (03_RICH_UI § 5); this
 * only widens the ingest source. The langgraph parser above is untouched.
 */
export function permissionRequestToPendingApproval(record: PermissionRequestRecord): PendingApproval {
    const tool = record.rawToolCall
    const preview = record.description ?? record.title ?? tool.title ?? ''
    return {
        proposal_id: record.requestId,
        decision_status: 'pending',
        tool_name: tool.resolvedKey || tool.innerToolName || tool.rawToolName || 'sandbox_permission',
        preview,
        payload: {
            options: record.options,
            input: tool.innerInput ?? tool.input,
            tool_call_id: record.toolCallId,
            request_id: record.requestId,
        },
        original_tool_call_id: record.toolCallId,
    }
}

/**
 * Resolve the ACP `optionId` for a binary approve/reject decision against the offered `options[]`.
 * The existing card only exposes approve/reject (+ optional feedback); the full kind->affordance
 * mapping lands in UI-C (03_RICH_UI § 5). Until then, bridge: approve picks the first allow option,
 * reject prefers `reject_with_feedback` when feedback is present, else the first reject option.
 * Returns null when no matching option exists so the caller can no-op rather than send a bad id.
 */
export function pickPermissionOptionId(
    options: PermissionOption[],
    decision: 'approve' | 'reject',
    hasFeedback: boolean
): string | null {
    if (decision === 'approve') {
        const allow = options.find((o) => o.kind === 'allow_once') ?? options.find((o) => o.kind === 'allow_always')
        return allow?.optionId ?? null
    }
    if (hasFeedback) {
        const withFeedback = options.find((o) => o.kind === 'reject_with_feedback')
        if (withFeedback) {
            return withFeedback.optionId
        }
    }
    const reject = options.find((o) => o.kind === 'reject') ?? options.find((o) => o.kind === 'reject_with_feedback')
    return reject?.optionId ?? null
}
