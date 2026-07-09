import { useValues } from 'kea'

import { IconNotebook, IconWarning } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { DangerousOperationResponse } from '~/queries/schema/schema-assistant-messages'

import { maxThreadLogic } from './maxThreadLogic'

/**
 * `plan_approval` reuses this card for sandbox plan-mode approvals — it only swaps the icon
 * and the awaiting copy. `dangerous_operation` is the existing LangGraph default.
 */
export type ApprovalCardVariant = 'dangerous_operation' | 'plan_approval'

interface DangerousOperationApprovalCardProps {
    operation: DangerousOperationResponse
    variant?: ApprovalCardVariant
}

/**
 * In-thread approval card that shows a compact summary of the approval status.
 * The actual approval interaction happens in the input area (DangerousOperationInput).
 */
export function DangerousOperationApprovalCard({
    operation,
    variant = 'dangerous_operation',
}: DangerousOperationApprovalCardProps): JSX.Element {
    // Read both resolvedApprovalStatuses (frontend) and pendingApprovalsData (backend)
    // to ensure we show correct status for both new and historical approvals
    const { resolvedApprovalStatuses, pendingApprovalsData, isSharedThread } = useValues(maxThreadLogic)

    // Frontend resolved status takes precedence over backend status
    const frontendResolved = resolvedApprovalStatuses[operation.proposalId]
    const backendData = pendingApprovalsData[operation.proposalId]
    const backendStatus = backendData?.decision_status

    // Determine the effective status and feedback
    const resolvedStatus = frontendResolved?.status ?? (backendStatus !== 'pending' ? backendStatus : undefined)
    const resolvedFeedback = frontendResolved?.feedback

    const subject = isSharedThread ? 'User' : 'You'

    const isPlan = variant === 'plan_approval'
    const Icon = isPlan ? IconNotebook : IconWarning

    // Show pending state while waiting for resolution
    if (!resolvedStatus) {
        return (
            <div className="flex text-xs text-muted">
                <div className="flex items-center justify-center size-5">
                    <Icon />
                </div>
                <div className="flex items-center gap-1 flex-1 min-w-0">
                    <span>{isPlan ? 'Awaiting plan approval...' : 'Awaiting approval...'}</span>
                    <Spinner className="size-3" />
                </div>
            </div>
        )
    }

    // Show resolved state
    const isApproved = resolvedStatus === 'approved'
    const text = isApproved
        ? `${subject} approved and executed this`
        : resolvedStatus === 'auto_rejected'
          ? `Skipped based on ${isSharedThread ? 'user' : 'your'} feedback`
          : resolvedFeedback
            ? `${subject} responded: "${resolvedFeedback}"`
            : `${subject} declined this operation`

    return (
        <div className="flex text-xs text-muted">
            <div className="flex items-center justify-center size-5">
                <Icon />
            </div>
            <div className="flex items-center gap-1 flex-1 min-w-0">
                <span>{text}</span>
            </div>
        </div>
    )
}
