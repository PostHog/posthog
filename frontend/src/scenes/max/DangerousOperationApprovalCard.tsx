import { useValues } from 'kea'

import { IconCheck, IconWarning, IconX } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { DangerousOperationResponse } from '~/queries/schema/schema-assistant-messages'

import { maxThreadLogic } from './maxThreadLogic'

interface DangerousOperationApprovalCardProps {
    operation: DangerousOperationResponse
}

/**
 * In-thread approval card that shows a compact summary of the approval status.
 * The actual approval interaction happens in the input area (DangerousOperationInput).
 */
export function DangerousOperationApprovalCard({ operation }: DangerousOperationApprovalCardProps): JSX.Element {
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

    // Show pending state while waiting for resolution
    if (!resolvedStatus) {
        return (
            <div className="flex items-center gap-2 text-muted text-xs">
                <IconWarning className="size-4" />
                <span>Awaiting approval...</span>
                <Spinner className="size-3" />
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
        <div className="flex items-center gap-1 text-xs text-muted">
            <IconWarning className="size-4" />
            <span>{text}</span>
            {isApproved ? <IconCheck className="text-success size-3" /> : <IconX className="text-danger size-3" />}
        </div>
    )
}
