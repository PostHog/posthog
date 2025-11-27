import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useState } from 'react'

import { IconDocument } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { SupportForm } from 'lib/components/Support/SupportForm'
import { supportLogic } from 'lib/components/Support/supportLogic'

import { MessageTemplate } from './messages/MessageTemplate'

export type FeedbackRating = 'bad' | 'okay' | 'good' | 'dismissed' | 'implicit_dismiss'
export type FeedbackTriggerType = 'message_interval' | 'random_sample' | 'manual' | 'retry' | 'cancel'

function captureNegativeFeedback(
    traceId: string | null,
    triggerType: FeedbackTriggerType,
    conversationId: string,
    feedbackText?: string
): void {
    posthog.capture('posthog_ai_feedback_submitted', {
        $ai_conversation_id: conversationId,
        $ai_session_id: conversationId,
        $ai_trace_id: traceId,
        $ai_feedback_rating: 'bad',
        $ai_feedback_trigger_type: triggerType,
        $ai_feedback_text: feedbackText || null,
    })
}

interface FeedbackPromptProps {
    conversationId: string
    traceId: string | null
    triggerType: FeedbackTriggerType
    onComplete: () => void
    onRecordCooldown: () => void
}

/**
 * Detailed feedback form shown after user clicks "Bad" rating.
 * Allows text feedback submission or escalation to support ticket.
 */
export function FeedbackPrompt({
    conversationId,
    traceId,
    triggerType,
    onComplete,
    onRecordCooldown,
}: FeedbackPromptProps): JSX.Element {
    const [feedbackText, setFeedbackText] = useState('')
    const [status, setStatus] = useState<'feedback' | 'ticket_preview' | 'done'>('feedback')
    const [isSubmitting, setIsSubmitting] = useState(false)
    const [isSupportModalOpen, setIsSupportModalOpen] = useState(false)

    const { sendSupportRequest, lastSubmittedTicketId } = useValues(supportLogic)
    const { resetSendSupportRequest, setSendSupportRequestValue, submitSendSupportRequest } = useActions(supportLogic)

    // Track when we're waiting for ticket submission to complete
    const [pendingTicketSubmission, setPendingTicketSubmission] = useState(false)
    // Track the ticket ID we had when starting submission to detect new tickets
    const [ticketIdBeforeSubmission, setTicketIdBeforeSubmission] = useState<string | null>(null)

    // Store the final message text when submitting ticket
    const [ticketMessageText, setTicketMessageText] = useState<string>('')

    useEffect(() => {
        // When ticket submission completes (lastSubmittedTicketId changes to a new value), capture the events
        if (pendingTicketSubmission && lastSubmittedTicketId && lastSubmittedTicketId !== ticketIdBeforeSubmission) {
            captureNegativeFeedback(traceId, triggerType, conversationId, ticketMessageText || undefined)

            posthog.capture('posthog_ai_support_ticket_created', {
                $ai_conversation_id: conversationId,
                $ai_session_id: conversationId,
                $ai_trace_id: traceId,
                $ai_support_ticket_id: lastSubmittedTicketId,
                $ai_feedback_rating: 'bad',
            })
            setIsSupportModalOpen(false)
            setPendingTicketSubmission(false)
            onComplete()
        }
    }, [
        lastSubmittedTicketId,
        pendingTicketSubmission,
        ticketIdBeforeSubmission,
        onComplete,
        conversationId,
        traceId,
        triggerType,
        ticketMessageText,
    ])

    function submitFeedback(): void {
        if (isSubmitting) {
            return
        }
        setIsSubmitting(true)
        onRecordCooldown()

        captureNegativeFeedback(traceId, triggerType, conversationId, feedbackText)

        setStatus('done')
        setTimeout(onComplete, 2000)
        setIsSubmitting(false)
    }

    function showTicketPreviewOrOpenModal(): void {
        if (feedbackText.trim().length > 0) {
            // Show preview if user entered feedback
            setStatus('ticket_preview')
        } else {
            // Skip preview and open modal directly if no feedback
            void openSupportModalWithPrefill()
        }
    }

    function openSupportModalWithPrefill(): void {
        resetSendSupportRequest({
            name: '',
            email: '',
            kind: 'feedback',
            target_area: 'max-ai',
            severity_level: 'low',
            message: feedbackText,
        })

        setIsSupportModalOpen(true)
    }

    function appendMetadataToMessage(message: string): string {
        const metadataLines = [`Conversation ID: ${conversationId}`, traceId ? `Trace ID: ${traceId}` : null].filter(
            Boolean
        )
        return message ? `${message}\n\n----\n${metadataLines.join('\n')}` : metadataLines.join('\n')
    }

    function handleSupportFormSubmit(): void {
        setTicketMessageText(sendSupportRequest.message)
        const finalMessage = appendMetadataToMessage(sendSupportRequest.message)

        setSendSupportRequestValue('message', finalMessage)
        setTicketIdBeforeSubmission(lastSubmittedTicketId)
        setPendingTicketSubmission(true)
        onRecordCooldown()
        submitSendSupportRequest()
    }

    function handleSupportModalCancel(): void {
        setIsSupportModalOpen(false)
        setPendingTicketSubmission(false)
    }

    const supportModal = (
        <LemonModal
            isOpen={isSupportModalOpen}
            onClose={handleSupportModalCancel}
            title="Give feedback"
            footer={
                <div className="flex items-center gap-2">
                    <LemonButton type="secondary" onClick={handleSupportModalCancel}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" data-attr="submit" onClick={handleSupportFormSubmit}>
                        Submit
                    </LemonButton>
                </div>
            }
        >
            <SupportForm />
        </LemonModal>
    )

    if (status === 'done') {
        return (
            <MessageTemplate type="ai">
                <p className="m-0 text-sm text-secondary">Thanks for making PostHog AI better!</p>
            </MessageTemplate>
        )
    }

    if (status === 'feedback') {
        return (
            <>
                <MessageTemplate type="ai">
                    <div className="flex flex-col gap-2">
                        <p className="m-0 font-medium">What could we improve?</p>
                        <LemonInput
                            placeholder="Help us improve PostHog AI..."
                            value={feedbackText}
                            onChange={setFeedbackText}
                            onPressEnter={submitFeedback}
                            fullWidth
                            autoFocus
                        />
                        <div className="flex gap-2">
                            <LemonButton type="primary" size="small" onClick={submitFeedback} loading={isSubmitting}>
                                Submit
                            </LemonButton>
                            <LemonButton type="secondary" size="small" onClick={showTicketPreviewOrOpenModal}>
                                Open support ticket
                            </LemonButton>
                        </div>
                    </div>
                </MessageTemplate>
                {supportModal}
            </>
        )
    }

    return (
        <>
            <MessageTemplate type="ai">
                <div className="flex flex-col gap-3">
                    <div className="flex items-center gap-2">
                        <IconDocument className="text-secondary" />
                        <span className="font-medium">Support ticket ready for review</span>
                    </div>
                    <p className="m-0 text-sm text-secondary">
                        Here's a draft of your support ticket. Please review and submit it to get help from PostHog
                        support.
                    </p>
                    <div className="bg-bg-light border rounded p-3">
                        <div className="text-xs font-medium text-secondary uppercase mb-1">Ticket description</div>
                        <p className="m-0 text-sm whitespace-pre-wrap">{feedbackText}</p>
                    </div>
                    <div>
                        <LemonButton type="primary" size="small" onClick={openSupportModalWithPrefill}>
                            Review support ticket
                        </LemonButton>
                    </div>
                </div>
            </MessageTemplate>
            {supportModal}
        </>
    )
}
