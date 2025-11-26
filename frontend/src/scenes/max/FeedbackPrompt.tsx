import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useState } from 'react'

import { IconDocument, IconX } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import api from 'lib/api'
import { SupportForm } from 'lib/components/Support/SupportForm'
import { supportLogic } from 'lib/components/Support/supportLogic'

import { MessageTemplate } from './messages/MessageTemplate'

export type FeedbackRating = 'bad' | 'okay' | 'good' | 'dismissed' | 'implicit_dismiss'
export type FeedbackTriggerType = 'message_interval' | 'random_sample' | 'manual' | 'retry' | 'cancel'

interface FeedbackPromptProps {
    conversationId: string
    traceId: string | null
    triggerType: FeedbackTriggerType
    onComplete: () => void
    onRecordCooldown: () => void
}

export function FeedbackPrompt({
    conversationId,
    traceId,
    triggerType,
    onComplete,
    onRecordCooldown,
}: FeedbackPromptProps): JSX.Element {
    const [rating, setRating] = useState<'bad' | 'okay' | 'good' | null>(null)
    const [feedbackText, setFeedbackText] = useState('')
    const [status, setStatus] = useState<'rating' | 'feedback' | 'ticket_preview' | 'done'>('rating')
    const [isSubmitting, setIsSubmitting] = useState(false)
    const [isSupportModalOpen, setIsSupportModalOpen] = useState(false)

    const { sendSupportRequest, isSupportFormOpen, lastSubmittedTicketId } = useValues(supportLogic)
    const { resetSendSupportRequest, setSendSupportRequestValue, submitSendSupportRequest } = useActions(supportLogic)

    // Track when form submission completes
    const [wasSubmitting, setWasSubmitting] = useState(false)
    // Store the feedback ID so we can update it with the support ticket ID
    const [feedbackId, setFeedbackId] = useState<string | null>(null)

    useEffect(() => {
        // When supportLogic closes the form after submission, close our modal too
        if (wasSubmitting && !isSupportFormOpen) {
            setIsSupportModalOpen(false)
            setWasSubmitting(false)

            // Update the feedback record with the support ticket ID
            if (feedbackId && lastSubmittedTicketId) {
                void api
                    .update(`api/environments/@current/conversations/${conversationId}/feedback/${feedbackId}/`, {
                        support_ticket_id: lastSubmittedTicketId,
                    })
                    .catch((e) => console.error('Failed to update feedback with ticket ID:', e))
            }

            onComplete()
        }
    }, [isSupportFormOpen, wasSubmitting, onComplete, feedbackId, lastSubmittedTicketId, conversationId])

    async function submitRating(selectedRating: 'bad' | 'okay' | 'good' | 'dismissed'): Promise<void> {
        if (isSubmitting) {
            return
        }

        // For 'bad' rating, just show the feedback form without saving to DB yet
        if (selectedRating === 'bad') {
            setRating('bad')
            setStatus('feedback')
            return
        }

        setIsSubmitting(true)
        onRecordCooldown()

        try {
            setRating(selectedRating === 'dismissed' ? null : selectedRating)

            await api.create(`api/environments/@current/conversations/${conversationId}/feedback/`, {
                rating: selectedRating,
                feedback_text: '',
                trigger_type: triggerType,
                trace_id: traceId || '',
            })

            if (traceId && selectedRating !== 'dismissed') {
                posthog.captureTraceMetric(traceId, 'quality', selectedRating)
            }

            // For dismiss, just hide immediately without showing "Thanks" message
            if (selectedRating === 'dismissed') {
                onComplete()
            } else {
                setStatus('done')
                setTimeout(onComplete, 2000)
            }
        } catch (e) {
            console.error('Failed to submit feedback rating:', e)
        } finally {
            setIsSubmitting(false)
        }
    }

    async function submitFeedback(): Promise<void> {
        if (isSubmitting) {
            return
        }
        setIsSubmitting(true)
        onRecordCooldown()

        try {
            if (traceId) {
                posthog.captureTraceMetric(traceId, 'quality', 'bad')
                if (feedbackText) {
                    posthog.captureTraceFeedback(traceId, feedbackText)
                }
            }

            await api.create(`api/environments/@current/conversations/${conversationId}/feedback/`, {
                rating: 'bad',
                feedback_text: feedbackText,
                trigger_type: triggerType,
                trace_id: traceId || '',
            })

            setStatus('done')
            setTimeout(onComplete, 2000)
        } catch (e) {
            console.error('Failed to submit feedback:', e)
        } finally {
            setIsSubmitting(false)
        }
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

    async function openSupportModalWithPrefill(): Promise<void> {
        onRecordCooldown()

        // Save feedback to our DB before opening support form
        try {
            if (traceId) {
                posthog.captureTraceMetric(traceId, 'quality', 'bad')
                if (feedbackText) {
                    posthog.captureTraceFeedback(traceId, feedbackText)
                }
            }

            const response = await api.create(`api/environments/@current/conversations/${conversationId}/feedback/`, {
                rating: 'bad',
                feedback_text: feedbackText,
                trigger_type: triggerType,
                trace_id: traceId || '',
            })

            // Store the feedback ID so we can update it with the support ticket ID later
            if (response && response.id) {
                setFeedbackId(response.id)
            }
        } catch (e) {
            console.error('Failed to save feedback before opening ticket:', e)
        }

        // Initialize the support form with pre-filled values (metadata added on submit)
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
        // Append metadata to the message transparently
        const finalMessage = appendMetadataToMessage(sendSupportRequest.message)

        setSendSupportRequestValue('message', finalMessage)
        setWasSubmitting(true)
        submitSendSupportRequest()
    }

    function handleSupportModalCancel(): void {
        setIsSupportModalOpen(false)
        setWasSubmitting(false)
        // User cancelled, so keep the ticket preview visible
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
                <p className="m-0 text-sm text-secondary">Thanks for your feedback!</p>
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
                            onPressEnter={() => void submitFeedback()}
                            fullWidth
                            autoFocus
                        />
                        <div className="flex gap-2">
                            <LemonButton
                                type="primary"
                                size="small"
                                onClick={() => void submitFeedback()}
                                loading={isSubmitting}
                            >
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

    if (status === 'ticket_preview') {
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
                            <LemonButton type="primary" size="small" onClick={() => void openSupportModalWithPrefill()}>
                                Review support ticket
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
                <div className="flex items-center gap-2">
                    <span className="text-sm">How is PostHog AI doing?</span>
                    <div className="flex gap-1">
                        <LemonButton
                            size="small"
                            type="secondary"
                            onClick={() => void submitRating('bad')}
                            loading={isSubmitting && rating === null}
                        >
                            Bad
                        </LemonButton>
                        <LemonButton
                            size="small"
                            type="secondary"
                            onClick={() => void submitRating('okay')}
                            loading={isSubmitting && rating === null}
                        >
                            Okay
                        </LemonButton>
                        <LemonButton
                            size="small"
                            type="secondary"
                            onClick={() => void submitRating('good')}
                            loading={isSubmitting && rating === null}
                        >
                            Good
                        </LemonButton>
                        <LemonButton
                            size="small"
                            type="tertiary"
                            icon={<IconX />}
                            onClick={() => void submitRating('dismissed')}
                            loading={isSubmitting && rating === null}
                        />
                    </div>
                </div>
            </MessageTemplate>
            {supportModal}
        </>
    )
}
