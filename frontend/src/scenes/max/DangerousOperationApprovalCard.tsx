import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCheck, IconWarning, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { ApprovalCardUIStatus, DangerousOperationResponse } from '~/queries/schema/schema-assistant-messages'

import { maxThreadLogic } from './maxThreadLogic'
import { MessageTemplate } from './messages/MessageTemplate'

interface DangerousOperationApprovalCardProps {
    operation: DangerousOperationResponse
    onResolved?: (approved: boolean) => void
}

export function DangerousOperationApprovalCard({
    operation,
    onResolved,
}: DangerousOperationApprovalCardProps): JSX.Element {
    // Local state tracks user-initiated loading states (approving, rejecting)
    const [localStatus, setLocalStatus] = useState<'pending' | 'approving' | 'rejecting'>('pending')

    // Use maxThreadLogic without explicit key to connect to the already-mounted instance
    // This ensures we receive the same state updates as the parent Thread component
    const { effectiveApprovalStatuses } = useValues(maxThreadLogic)
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

    return (
        <MessageTemplate type="ai" boxClassName="border-warning p-0 overflow-hidden">
            <div className="bg-warning-highlight px-4 py-2 border-b border-warning flex items-center gap-2">
                <IconWarning className="text-warning size-4" />
                <span className="font-medium text-sm">Approval required</span>
            </div>

            <div className="p-4">
                <p className="text-sm text-secondary mb-3">This operation will make the following changes:</p>
                <pre className="text-sm bg-bg-light p-3 rounded whitespace-pre-wrap font-mono m-0">
                    {operation.preview}
                </pre>
            </div>

            <div className="px-4 py-3 bg-bg-light border-t flex items-center justify-between">
                {displayStatus === 'pending' && (
                    <>
                        <span className="text-xs text-muted">Review the changes above before approving</span>
                        <div className="flex gap-2">
                            <LemonButton
                                size="small"
                                type="secondary"
                                status="danger"
                                icon={<IconX />}
                                onClick={handleReject}
                            >
                                Reject
                            </LemonButton>
                            <LemonButton size="small" type="primary" icon={<IconCheck />} onClick={handleApprove}>
                                Approve
                            </LemonButton>
                        </div>
                    </>
                )}

                {displayStatus === 'approving' && (
                    <div className="flex items-center gap-2 text-muted ml-auto">
                        <LemonButton size="small" type="primary" loading>
                            Applying...
                        </LemonButton>
                    </div>
                )}

                {displayStatus === 'approved' && (
                    <div className="flex items-center gap-2 text-success ml-auto">
                        <IconCheck className="size-4" />
                        <span className="text-sm font-medium">Changes applied</span>
                    </div>
                )}

                {displayStatus === 'rejecting' && (
                    <div className="flex items-center gap-2 text-muted ml-auto">
                        <LemonButton size="small" type="secondary" loading>
                            Rejecting...
                        </LemonButton>
                    </div>
                )}

                {displayStatus === 'rejected' && (
                    <div className="flex items-center gap-2 text-muted ml-auto">
                        <IconX className="size-4" />
                        <span className="text-sm">Rejected</span>
                    </div>
                )}

                {displayStatus === 'auto_rejected' && (
                    <div className="flex items-center gap-2 text-muted ml-auto">
                        <IconX className="size-4" />
                        <span className="text-sm">Rejected (with feedback)</span>
                    </div>
                )}
            </div>
        </MessageTemplate>
    )
}
