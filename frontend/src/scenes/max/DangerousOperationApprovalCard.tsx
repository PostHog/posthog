import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCheck, IconWarning, IconX } from '@posthog/icons'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'

import { ApprovalCardUIStatus, DangerousOperationResponse } from '~/queries/schema/schema-assistant-messages'

import { maxThreadLogic } from './maxThreadLogic'
import { MessageTemplate } from './messages/MessageTemplate'

interface DangerousOperationApprovalCardProps {
    operation: DangerousOperationResponse
    onResolved?: (approved: boolean) => void
}

function CompactStatusDisplay({
    status,
    isSharedThread,
}: {
    status: 'approved' | 'rejected' | 'auto_rejected'
    isSharedThread: boolean
}): JSX.Element {
    const isApproved = status === 'approved'
    const subject = isSharedThread ? 'User' : 'You'
    const text = isApproved
        ? `${subject} approved and executed this`
        : status === 'auto_rejected'
          ? `Skipped based on ${isSharedThread ? 'user' : 'your'} feedback`
          : `${subject} declined this operation`

    return (
        <div className="flex flex-col rounded transition-all duration-500 flex-1 min-w-0 text-xs">
            <div className="transition-all duration-500 flex select-none text-default">
                <div className="flex items-center justify-center size-5">
                    <span className="inline-flex">
                        <IconWarning />
                    </span>
                </div>
                <div className="flex items-center gap-1 flex-1 min-w-0 h-full">
                    <div>
                        <span className="inline-flex">{text}</span>
                    </div>
                    {isApproved ? (
                        <IconCheck className="text-success size-3" />
                    ) : (
                        <IconX className="text-danger size-3" />
                    )}
                </div>
            </div>
        </div>
    )
}

export function DangerousOperationApprovalCard({
    operation,
    onResolved,
}: DangerousOperationApprovalCardProps): JSX.Element {
    // Local state tracks user-initiated loading states (approving, rejecting)
    const [localStatus, setLocalStatus] = useState<'pending' | 'approving' | 'rejecting'>('pending')

    // Use maxThreadLogic without explicit key to connect to the already-mounted instance
    // This ensures we receive the same state updates as the parent Thread component
    const { effectiveApprovalStatuses, isSharedThread } = useValues(maxThreadLogic)
    const { continueAfterApproval, continueAfterRejection } = useActions(maxThreadLogic)

    const resolvedStatus = effectiveApprovalStatuses[operation.proposalId]

    const displayStatus: ApprovalCardUIStatus = (() => {
        if (localStatus === 'approving' || localStatus === 'rejecting') {
            // Check if the operation completed while we were loading
            if (resolvedStatus === 'approved' || resolvedStatus === 'rejected' || resolvedStatus === 'auto_rejected') {
                return resolvedStatus
            }
            return localStatus
        }
        if (resolvedStatus && resolvedStatus !== 'pending') {
            return resolvedStatus
        }
        return 'pending'
    })()

    const handleApprove = (): void => {
        setLocalStatus('approving')
        // Resume conversation with approval
        continueAfterApproval(operation.proposalId)
        onResolved?.(true)
    }

    const handleReject = (): void => {
        setLocalStatus('rejecting')
        // Resume conversation with rejection
        continueAfterRejection(operation.proposalId)
        onResolved?.(false)
    }

    // Show compact display for resolved statuses
    if (displayStatus === 'approved' || displayStatus === 'rejected' || displayStatus === 'auto_rejected') {
        return <CompactStatusDisplay status={displayStatus} isSharedThread={isSharedThread} />
    }

    return (
        <MessageTemplate type="ai" boxClassName="border-warning p-0 overflow-hidden text-xs">
            <div className="bg-warning-highlight p-2 border-b border-warning flex items-center gap-2">
                <IconWarning className="text-warning size-3" />
                <span className="font-medium">Approval required</span>
            </div>

            <div className="p-2 pb-0">
                <p className="text-secondary mb-2">This operation will make the following changes:</p>
                <p className="text-secondary m-0 whitespace-pre">{operation.preview}</p>
            </div>

            <LemonDivider />

            <div className="p-2 pt-0 flex items-center justify-between gap-1.5">
                {displayStatus === 'pending' && (
                    <>
                        <span className="text-muted">Review the changes above before approving</span>
                        <div className="flex gap-2">
                            <LemonButton
                                size="xsmall"
                                type="secondary"
                                status="danger"
                                icon={<IconX />}
                                onClick={handleReject}
                            >
                                Reject
                            </LemonButton>
                            <LemonButton size="xsmall" type="primary" icon={<IconCheck />} onClick={handleApprove}>
                                Approve
                            </LemonButton>
                        </div>
                    </>
                )}

                {(displayStatus === 'rejecting' || displayStatus === 'approving') && (
                    <div className="flex items-center gap-2 text-muted ml-auto">
                        <LemonButton size="xsmall" type="primary" loading>
                            {displayStatus === 'rejecting' ? 'Rejecting...' : 'Approving...'}
                        </LemonButton>
                    </div>
                )}
            </div>
        </MessageTemplate>
    )
}
