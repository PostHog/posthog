import { useActions } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import api from 'lib/api'
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
    const [status, setStatus] = useState<'rating' | 'feedback' | 'done'>('rating')
    const [isSubmitting, setIsSubmitting] = useState(false)

    const { openSupportForm } = useActions(supportLogic)

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

    async function openTicket(): Promise<void> {
        onRecordCooldown()

        // Save feedback to our DB before opening support form
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
        } catch (e) {
            console.error('Failed to save feedback before opening ticket:', e)
        }

        // Build message with user feedback first, then metadata
        const metadataLines = [`Conversation ID: ${conversationId}`, traceId ? `Trace ID: ${traceId}` : null].filter(
            Boolean
        )

        const message = feedbackText ? `${feedbackText}\n\n---\n${metadataLines.join('\n')}` : metadataLines.join('\n')

        openSupportForm({
            kind: 'feedback',
            target_area: 'max-ai',
            message,
        })
        onComplete()
    }

    if (status === 'done') {
        return (
            <MessageTemplate type="ai">
                <p className="m-0 text-sm text-secondary">Thanks for your feedback!</p>
            </MessageTemplate>
        )
    }

    if (status === 'feedback') {
        return (
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
                        <LemonButton type="secondary" size="small" onClick={() => void openTicket()}>
                            Open support ticket
                        </LemonButton>
                    </div>
                </div>
            </MessageTemplate>
        )
    }

    return (
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
    )
}
