import { useActions } from 'kea'
import { useCallback, useEffect } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

import { SupportForm } from 'lib/components/Support/SupportForm'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { SupportTicketMessage } from '~/queries/schema'

interface SupportTicketFromThreadModalProps {
    ticketData: SupportTicketMessage['ticket_data']
    onSubmitted?: (ticketId?: string) => void
    onSubmitRef?: (submitFn: () => Promise<void>) => void
}

export function SupportTicketFromThreadModal({
    ticketData,
    onSubmitted,
    onSubmitRef,
}: SupportTicketFromThreadModalProps): JSX.Element {
    const { resetSendSupportRequest, submitSendSupportRequest } = useActions(supportLogic)

    // Pre-fill the form with data from Max
    useEffect(() => {
        const formattedMessage = `Hi,

I've had a conversation with PostHog AI, here's the summary:

> ${ticketData.summary}

Thanks,`

        resetSendSupportRequest({
            kind: 'support', // Default to support ticket
            target_area: ticketData.target_area as any,
            severity_level:
                ticketData.priority === 'critical'
                    ? 'critical'
                    : ticketData.priority === 'high'
                      ? 'high'
                      : ticketData.priority === 'low'
                        ? 'low'
                        : 'medium',
            message: formattedMessage,
            name: '',
            email: '',
            tags: ['posthog_ai_escalated'],
        })
    }, [ticketData, resetSendSupportRequest])

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

            <SupportForm />

            <LemonBanner type="info">
                <div className="text-sm">
                    <strong>Note:</strong> Our support team will have access to the full conversation history to help
                    understand your issue.
                </div>
            </LemonBanner>
        </div>
    )
}
