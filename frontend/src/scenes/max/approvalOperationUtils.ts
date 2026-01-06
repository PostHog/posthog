import { DangerousOperationResponse } from '~/queries/schema/schema-assistant-messages'

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
        r.status === 'pending_approval' &&
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

/**
 * Normalize a dangerous operation response to consistent camelCase format.
 * Accepts both snake_case backend responses and already-normalized responses.
 * Should only be called after isDangerousOperationResponse validates the input.
 */
export function normalizeDangerousOperationResponse(
    result: DangerousOperationResponseLike | DangerousOperationResponse
): DangerousOperationResponse {
    // Handle both camelCase and snake_case field names from backend
    // Fallback values are defensive - isDangerousOperationResponse should validate all fields first
    const r = result as DangerousOperationResponseLike
    return {
        status: 'pending_approval',
        proposalId: r.proposalId ?? r.proposal_id ?? '',
        toolName: r.toolName ?? r.tool_name ?? '',
        preview: r.preview ?? '',
        payload: r.payload ?? {},
    }
}

export type ApprovalStatus = 'approved' | 'rejected'

/**
 * Messages sent when user clicks approve/reject buttons.
 */
export const APPROVAL_MESSAGES = {
    approved: 'Yes, proceed with this change.',
    rejected: "I don't want to make this change.",
} as const
