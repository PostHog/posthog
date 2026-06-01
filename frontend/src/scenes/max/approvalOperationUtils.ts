import { DangerousOperationResponse, PENDING_APPROVAL_STATUS } from '~/queries/schema/schema-assistant-messages'

import type { PermissionOption } from './types/sandboxStreamTypes'

/**
 * The card-facing decision a user can take on an approval option. The existing
 * LangGraph card resolves to `approved` / `declined` / `auto_rejected`; the sandbox
 * runtime surfaces richer ACP option kinds that map down onto the same model.
 */
export type ApprovalDecision = 'approved' | 'declined'

/**
 * One button the sandbox approval card renders, derived from an ACP `permission_request`
 * option. The card forwards `optionId` back verbatim on the `permission_response`.
 * See docs/internal/posthog-ai-migration/03_RICH_UI.md § 5.2.
 */
export interface ApprovalCardOption {
    optionId: string
    label: string
    /** Resolution status the card records once this option is chosen. */
    decision: ApprovalDecision
    /** Primary CTA styling (the single `allow_once`/approve path). */
    primary: boolean
    /** `allow_always` — only shown when the tool preview opts in via `remember: true`. */
    remembered: boolean
    /** `reject_with_feedback` — the card opens a feedback text input before sending. */
    requiresFeedback: boolean
}

/**
 * Maps ACP `permission_request` option kinds onto the sandbox approval card's option model
 * (03_RICH_UI.md § 5.2). The wire `optionId`/`name` are preserved so the card can forward the
 * chosen `optionId` straight back on the `permission_response` — the kind only drives UI affordance
 * and the resolution status recorded locally.
 *
 * `allow_always` is hidden unless `allowRemember` is true (the tool preview must carry
 * `remember: true`); the option is still returned so callers can decide, but flagged via
 * `remembered` so the renderer can drop it.
 */
export function mapPermissionOption(option: PermissionOption): ApprovalCardOption {
    switch (option.kind) {
        case 'allow_once':
            return {
                optionId: option.optionId,
                label: option.name || 'Approve',
                decision: 'approved',
                primary: true,
                remembered: false,
                requiresFeedback: false,
            }
        case 'allow_always':
            return {
                optionId: option.optionId,
                label: option.name || 'Approve always',
                decision: 'approved',
                primary: false,
                remembered: true,
                requiresFeedback: false,
            }
        case 'reject':
            return {
                optionId: option.optionId,
                label: option.name || 'Decline',
                decision: 'declined',
                primary: false,
                remembered: false,
                requiresFeedback: false,
            }
        case 'reject_with_feedback':
            return {
                optionId: option.optionId,
                label: option.name || 'Decline with feedback…',
                decision: 'declined',
                primary: false,
                remembered: false,
                requiresFeedback: true,
            }
    }
}

/**
 * Maps the full ACP `options[]` to card options, dropping `allow_always` unless the tool
 * preview opted into a rememberable decision (`allowRemember`). See 03_RICH_UI.md § 5.2.
 */
export function mapPermissionOptions(
    options: PermissionOption[],
    allowRemember: boolean = false
): ApprovalCardOption[] {
    return options.map(mapPermissionOption).filter((option) => !option.remembered || allowRemember)
}

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
