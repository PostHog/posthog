import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCheck, IconWarning, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { ApprovalCardStatus, DangerousOperationResponse } from '~/queries/schema/schema-assistant-messages'

import { maxLogic } from './maxLogic'
import { maxThreadLogic } from './maxThreadLogic'
import { MessageTemplate } from './messages/MessageTemplate'

export { isDangerousOperationResponse, normalizeDangerousOperationResponse } from './approvalOperationUtils'

interface DangerousOperationApprovalCardProps {
    operation: DangerousOperationResponse
    conversationId: string
    initialStatus?: 'approved' | 'rejected' | 'auto_rejected'
    onResolved?: (approved: boolean) => void
}

export function DangerousOperationApprovalCard({
    operation,
    conversationId,
    initialStatus,
    onResolved,
}: DangerousOperationApprovalCardProps): JSX.Element {
    const [status, setStatus] = useState<ApprovalCardStatus>(initialStatus ?? 'pending')
    const { tabId } = useValues(maxLogic)
    const { continueAfterApproval, continueAfterRejection } = useActions(maxThreadLogic({ conversationId, tabId }))

    const handleApprove = async (): Promise<void> => {
        setStatus('approving')
        try {
            // 1. Mark operation as approved in backend
            await api.conversations.approveOperation(conversationId, operation.proposalId)
            // 2. Update card status
            setStatus('approved')
            // 3. Continue conversation - agent will execute the approved operation
            continueAfterApproval(operation.proposalId)
            onResolved?.(true)
        } catch (e: any) {
            if (e.status === 404) {
                setStatus('expired')
                lemonToast.error('This operation has expired')
            } else {
                setStatus('pending')
                lemonToast.error('Failed to approve operation')
            }
        }
    }

    const handleReject = async (): Promise<void> => {
        setStatus('rejecting')
        try {
            // 1. Delete the pending operation from backend
            await api.conversations.rejectOperation(conversationId, operation.proposalId)
            // 2. Update card status
            setStatus('rejected')
            // 3. Continue conversation with rejection message
            continueAfterRejection(operation.proposalId)
            onResolved?.(false)
        } catch (e: any) {
            if (e.status === 404) {
                setStatus('expired')
                lemonToast.error('This operation has expired')
            } else {
                setStatus('pending')
                lemonToast.error('Failed to reject operation')
            }
        }
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
                {status === 'pending' && (
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

                {status === 'approving' && (
                    <div className="flex items-center gap-2 text-muted ml-auto">
                        <LemonButton size="small" type="primary" loading>
                            Applying...
                        </LemonButton>
                    </div>
                )}

                {status === 'approved' && (
                    <div className="flex items-center gap-2 text-success ml-auto">
                        <IconCheck className="size-4" />
                        <span className="text-sm font-medium">Changes applied</span>
                    </div>
                )}

                {status === 'rejecting' && (
                    <div className="flex items-center gap-2 text-muted ml-auto">
                        <LemonButton size="small" type="secondary" loading>
                            Rejecting...
                        </LemonButton>
                    </div>
                )}

                {status === 'rejected' && (
                    <div className="flex items-center gap-2 text-muted ml-auto">
                        <IconX className="size-4" />
                        <span className="text-sm">Rejected</span>
                    </div>
                )}

                {status === 'auto_rejected' && (
                    <div className="flex items-center gap-2 text-muted ml-auto">
                        <IconX className="size-4" />
                        <span className="text-sm">Skipped (new message sent)</span>
                    </div>
                )}

                {status === 'expired' && (
                    <div className="flex items-center gap-2 text-danger ml-auto">
                        <IconWarning className="size-4" />
                        <span className="text-sm">Expired</span>
                    </div>
                )}
            </div>
        </MessageTemplate>
    )
}
