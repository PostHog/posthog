import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCheck, IconWarning, IconX } from '@posthog/icons'
import { LemonDivider } from '@posthog/lemon-ui'

import { DangerousOperationResponse } from '~/queries/schema/schema-assistant-messages'

import { MarkdownMessage, type Option, OptionSelector } from 'products/posthog_ai/frontend/api/primitives'

import { maxThreadLogic } from '../maxThreadLogic'

interface DangerousOperationInputProps {
    operation: DangerousOperationResponse
}

export function DangerousOperationInput({ operation }: DangerousOperationInputProps): JSX.Element {
    const { continueAfterApproval, continueAfterRejection } = useActions(maxThreadLogic)
    const { streamingActive } = useValues(maxThreadLogic)
    const [status, setStatus] = useState<'pending' | 'approving' | 'rejecting' | 'custom'>('pending')

    const options: Option[] = [
        { label: 'Approve and execute', value: 'approve', icon: <IconCheck /> },
        { label: 'Reject this operation', value: 'reject', icon: <IconX /> },
    ]

    const handleSelect = (value: string | null): void => {
        if (value === 'approve') {
            setStatus('approving')
            continueAfterApproval(operation.proposalId)
        } else if (value === 'reject') {
            setStatus('rejecting')
            continueAfterRejection(operation.proposalId)
        }
    }

    const handleCustomSubmit = (customResponse: string): void => {
        setStatus('custom')
        continueAfterRejection(operation.proposalId, customResponse)
    }

    const isLoading = status !== 'pending'

    return (
        <div className="flex flex-col gap-2 p-3" data-attr="max-dangerous-operation-input">
            <div className="flex items-center gap-2 text-sm">
                <IconWarning className="text-warning size-4" />
                <span className="font-medium">Approval required</span>
            </div>
            {operation.toolName !== 'finalize_plan' && (
                <p className="text-xs text-secondary m-0">Review the changes below before approving:</p>
            )}
            <LemonDivider className="my-0 -mx-3 w-[calc(100%+var(--spacing)*6)]" />
            <div className="max-h-60 overflow-y-auto">
                <MarkdownMessage content={operation.preview} id={`approval-${operation.proposalId}`} />
            </div>
            <LemonDivider className="my-0 -mx-3 w-[calc(100%+var(--spacing)*6)]" />
            <OptionSelector
                options={options}
                onSelect={handleSelect}
                allowCustom
                customPlaceholder="Explain what you'd like instead..."
                onCustomSubmit={handleCustomSubmit}
                disabled={streamingActive}
                loading={isLoading}
                loadingMessage={
                    status === 'approving'
                        ? 'Approving...'
                        : status === 'custom'
                          ? 'Sending response...'
                          : 'Rejecting...'
                }
            />
        </div>
    )
}
