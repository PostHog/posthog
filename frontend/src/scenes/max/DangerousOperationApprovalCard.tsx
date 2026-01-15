import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCheck, IconWarning, IconX } from '@posthog/icons'
import { LemonDivider } from '@posthog/lemon-ui'

import { ApprovalCardUIStatus, DangerousOperationResponse } from '~/queries/schema/schema-assistant-messages'

import { OptionSelector } from './components/OptionSelector'
import { maxThreadLogic } from './maxThreadLogic'
import { MessageTemplate } from './messages/MessageTemplate'

interface DangerousOperationApprovalCardProps {
    operation: DangerousOperationResponse
    onResolved?: (approved: boolean) => void
}

const APPROVE_VALUE = 'approve'
const REJECT_VALUE = 'reject'

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
    const [localStatus, setLocalStatus] = useState<'pending' | 'approving' | 'rejecting' | 'custom'>('pending')

    const { effectiveApprovalStatuses, isSharedThread } = useValues(maxThreadLogic)
    const { continueAfterApproval, continueAfterRejection } = useActions(maxThreadLogic)

    const resolvedStatus = effectiveApprovalStatuses[operation.proposalId]

    const displayStatus: ApprovalCardUIStatus = (() => {
        if (localStatus === 'approving' || localStatus === 'rejecting' || localStatus === 'custom') {
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

    const handleSelect = (value: string): void => {
        if (value === APPROVE_VALUE) {
            setLocalStatus('approving')
            continueAfterApproval(operation.proposalId)
            onResolved?.(true)
        } else if (value === REJECT_VALUE) {
            setLocalStatus('rejecting')
            continueAfterRejection(operation.proposalId)
            onResolved?.(false)
        }
    }

    const handleCustomSubmit = (customResponse: string): void => {
        setLocalStatus('custom')
        continueAfterRejection(operation.proposalId, customResponse)
        onResolved?.(false)
    }

    const isLoading = displayStatus === 'approving' || displayStatus === 'rejecting' || displayStatus === 'custom'
    const loadingMessage =
        displayStatus === 'approving'
            ? 'Approving...'
            : displayStatus === 'custom'
              ? 'Sending response...'
              : 'Rejecting...'

    if (displayStatus === 'approved' || displayStatus === 'rejected' || displayStatus === 'auto_rejected') {
        return <CompactStatusDisplay status={displayStatus} isSharedThread={isSharedThread} />
    }

    const options = [
        { label: 'Approve and execute', value: APPROVE_VALUE, icon: <IconCheck /> },
        { label: 'Reject this operation', value: REJECT_VALUE, icon: <IconX /> },
    ]

    return (
        <MessageTemplate type="ai" boxClassName="border-warning p-0 overflow-hidden text-xs">
            <div className="bg-warning-highlight p-2 border-b border-warning flex items-center gap-2">
                <IconWarning className="text-warning size-3" />
                <span className="font-medium">Approval required</span>
            </div>

            <div className="p-2 pb-0">
                <p className="text-secondary mb-3">This operation will make the following changes:</p>
                <pre className="bg-bg-light rounded whitespace-pre-wrap font-mono m-0">{operation.preview}</pre>
            </div>

            <LemonDivider />

            <div className="p-2 pt-0">
                <OptionSelector
                    options={options}
                    onSelect={handleSelect}
                    allowCustom
                    customPlaceholder="Type something..."
                    onCustomSubmit={handleCustomSubmit}
                    loading={isLoading}
                    loadingMessage={loadingMessage}
                />
            </div>
        </MessageTemplate>
    )
}
