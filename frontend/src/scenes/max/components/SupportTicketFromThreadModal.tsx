import { useActions } from 'kea'
import { useCallback, useEffect } from 'react'

import { SupportForm } from 'lib/components/Support/SupportForm'
import { supportLogic } from 'lib/components/Support/supportLogic'

import { DraftSupportTicketToolOutput } from '~/queries/schema/schema-assistant-messages'

interface SupportTicketFromThreadModalProps {
    draftTicketData: DraftSupportTicketToolOutput
    onSubmitted?: (ticketId?: string) => void
    onSubmitRef?: (submitFn: () => Promise<void>) => void
}

export function SupportTicketFromThreadModal({
    draftTicketData,
    onSubmitted,
    onSubmitRef,
}: SupportTicketFromThreadModalProps): JSX.Element {
    const { resetSendSupportRequest, submitSendSupportRequest } = useActions(supportLogic)

    // Pre-fill the form with data from Max
    useEffect(() => {
        const formattedMessage = `Hi,

I've had a conversation with PostHog AI, here's the summary:

> ${draftTicketData.summary}

Thanks,`

        resetSendSupportRequest({
            kind: 'support', // Default to support ticket
            target_area: draftTicketData.target_area as any,
            severity_level:
                draftTicketData.priority === 'critical'
                    ? 'critical'
                    : draftTicketData.priority === 'high'
                      ? 'high'
                      : draftTicketData.priority === 'low'
                        ? 'low'
                        : 'medium',
            message: formattedMessage,
            name: '',
            email: '',
            tags: ['posthog_ai_escalated'],
        })
    }, [draftTicketData, resetSendSupportRequest])

    const handleSubmit = useCallback(async (): Promise<void> => {
        try {
            await submitSendSupportRequest()
            onSubmitted?.()
        } catch (error) {
            console.error('Failed to submit support ticket:', error)
            throw error
        }
    }, [submitSendSupportRequest, onSubmitted])

    useEffect(() => {
        onSubmitRef?.(handleSubmit)
    }, [onSubmitRef, handleSubmit])

    return (
        <div className="space-y-4">
            <p className="text-muted text-sm">
                Here's a draft support ticket with a summary of your conversation. You can review and submit it below:
            </p>

            <SupportForm attachPostHogAIConversation />
        </div>
    )
}
