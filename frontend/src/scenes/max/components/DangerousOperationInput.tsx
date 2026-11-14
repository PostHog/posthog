import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCheck, IconWarning, IconX } from '@posthog/icons'
import { LemonDivider } from '@posthog/lemon-ui'

import { DangerousOperationResponse } from '~/queries/schema/schema-assistant-messages'

import { MarkdownMessage, type Option, OptionSelector } from 'products/posthog_ai/frontend/api/primitives'

import { maxThreadLogic } from '../maxThreadLogic'

interface DangerousOperationInputProps {
    operations: DangerousOperationResponse[]
}

export function DangerousOperationInput({ operations }: DangerousOperationInputProps): JSX.Element {
    const { continueAfterApproval, continueAfterApprovals, continueAfterRejection } = useActions(maxThreadLogic)
    const { streamingActive } = useValues(maxThreadLogic)
    const [status, setStatus] = useState<'pending' | 'approving' | 'rejecting' | 'custom'>('pending')
    const proposalIds = operations.map((operation) => operation.proposalId)
    const firstOperation = operations[0]

    const options: Option[] = [
        { label: 'Approve this change', value: 'approve', icon: <IconCheck /> },
        ...(operations.length > 1 && operations.every((operation) => operation.toolName === 'create_insight')
            ? [
                  {
                      label: `Approve all ${operations.length} insight edits`,
                      value: 'approve_all',
                      icon: <IconCheck />,
                  },
              ]
            : []),
        { label: 'Reject this operation', value: 'reject', icon: <IconX /> },
    ]

    const handleSelect = (value: string | null): void => {
        if (value === 'approve') {
            setStatus('approving')
            continueAfterApproval(firstOperation.proposalId)
        } else if (value === 'approve_all') {
            setStatus('approving')
            continueAfterApprovals(proposalIds)
        } else if (value === 'reject') {
            setStatus('rejecting')
            continueAfterRejection(firstOperation.proposalId)
        }
    }

    const handleCustomSubmit = (customResponse: string): void => {
        setStatus('custom')
        continueAfterRejection(firstOperation.proposalId, customResponse)
    }

    const isLoading = status !== 'pending'

    return (
        <div className="flex flex-col gap-2 p-3" data-attr="max-dangerous-operation-input">
            <div className="flex items-center gap-2 text-sm">
                <IconWarning className="text-warning size-4" />
                <span className="font-medium">Approval required</span>
            </div>
            {operations.length > 1 || firstOperation.toolName !== 'finalize_plan' ? (
                <p className="text-xs text-secondary m-0">Review the changes below before approving:</p>
            ) : null}
            <LemonDivider className="my-0 -mx-3 w-[calc(100%+var(--spacing)*6)]" />
            <div className="max-h-60 overflow-y-auto">
                {operations.map((operation) => (
                    <MarkdownMessage
                        key={operation.proposalId}
                        content={operation.preview}
                        id={`approval-${operation.proposalId}`}
                    />
                ))}
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
