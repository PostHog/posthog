import { DangerousOperationResponse, PENDING_APPROVAL_STATUS } from '~/queries/schema/schema-assistant-messages'

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
