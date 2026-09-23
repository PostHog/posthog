import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconDocument } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, lemonToast } from '@posthog/lemon-ui'

import { SupportForm } from 'lib/components/Support/SupportForm'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { userLogic } from 'scenes/userLogic'

import { MessageTemplate } from 'products/posthog_ai/frontend/api/primitives'

import { feedbackPromptLogic } from './feedbackPromptLogic'
import { appendTicketMetadata } from './ticketUtils'
import { captureFeedback } from './utils'

interface FeedbackPromptProps {
    conversationId: string
    traceId: string | null
}

// Duplicated for the sandbox runtime in products/posthog_ai/frontend/components/FeedbackPromptDetails.tsx; this copy is deleted with the LangGraph runtime.
/**
 * Detailed feedback form shown after user clicks "Bad" rating.
 * Allows text feedback submission or escalation to support ticket.
 */
export function FeedbackPrompt({ conversationId, traceId }: FeedbackPromptProps): JSX.Element {
    const { currentTriggerType } = useValues(feedbackPromptLogic({ conversationId }))
    const { recordFeedbackShown, completeDetailedFeedback } = useActions(feedbackPromptLogic({ conversationId }))
    const [feedbackText, setFeedbackText] = useState('')
    const [status, setStatus] = useState<'feedback' | 'ticket_preview' | 'done'>('feedback')
    const [isSubmitting, setIsSubmitting] = useState(false)
    const [hasSubmittedTicket, setHasSubmittedTicket] = useState(false)
    const [isSupportModalOpen, setIsSupportModalOpen] = useState(false)

    const submitInFlightRef = useRef(false)

    const { sendSupportRequest, lastSubmittedTicketId } = useValues(supportLogic)
    const { resetSendSupportRequest } = useActions(supportLogic)
    const { user } = useValues(userLogic)

    // Track when we're waiting for ticket submission to complete
    const [pendingTicketSubmission, setPendingTicketSubmission] = useState(false)
    // Track the ticket ID we had when starting submission to detect new tickets
    const [ticketIdBeforeSubmission, setTicketIdBeforeSubmission] = useState<string | null>(null)

    // Store the final message text when submitting ticket
    const [ticketMessageText, setTicketMessageText] = useState<string>('')

    useEffect(() => {
        // When ticket submission completes (lastSubmittedTicketId changes to a new value), capture the events
        if (pendingTicketSubmission && lastSubmittedTicketId && lastSubmittedTicketId !== ticketIdBeforeSubmission) {
            captureFeedback(conversationId, traceId, 'bad', currentTriggerType, ticketMessageText || undefined)

            // The posthog_ai_support_ticket_created event (with $ai_feedback_rating) is captured in
            // supportLogic once the ticket id resolves, so it fires on every submit path.
            submitInFlightRef.current = false
            setHasSubmittedTicket(true)
            setIsSupportModalOpen(false)
            setPendingTicketSubmission(false)
            completeDetailedFeedback()
        }
    }, [
        lastSubmittedTicketId,
        pendingTicketSubmission,
        ticketIdBeforeSubmission,
        completeDetailedFeedback,
        conversationId,
        traceId,
        currentTriggerType,
        ticketMessageText,
    ])

    function submitFeedback(): void {
        if (isSubmitting) {
            return
        }
        setIsSubmitting(true)
        recordFeedbackShown()

        captureFeedback(conversationId, traceId, 'bad', currentTriggerType, feedbackText)

        setStatus('done')
        setTimeout(completeDetailedFeedback, 2000)
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
        if (hasSubmittedTicket) {
            return
        }
        resetSendSupportRequest({
            name: '',
            email: '',
            kind: 'feedback',
            message: feedbackText,
            ai_conversation_id: conversationId,
            ai_trace_id: traceId,
            ai_feedback_rating: 'bad',
        })

        setIsSupportModalOpen(true)
    }

    async function handleSupportFormSubmit(): Promise<void> {
        if (submitInFlightRef.current || hasSubmittedTicket) {
            return
        }

        const finalMessage = appendTicketMetadata(sendSupportRequest.message, { conversationId, traceId })
        if (!finalMessage) {
            lemonToast.error('Please add a description before creating a ticket.')
            return
        }

        submitInFlightRef.current = true
        setTicketMessageText(sendSupportRequest.message)
        const ticketIdBefore = supportLogic.values.lastSubmittedTicketId
        setTicketIdBeforeSubmission(ticketIdBefore)
        setPendingTicketSubmission(true)
        recordFeedbackShown()
        try {
            await supportLogic.asyncActions.submitSupportTicket({
                ...sendSupportRequest,
                name: user?.first_name ?? sendSupportRequest.name ?? 'name not set',
                email: user?.email ?? sendSupportRequest.email ?? '',
                message: finalMessage,
            })
        } catch {
            // Failure is detected below via the unchanged ticket id
        }
        // Success closes the modal via the effect watching lastSubmittedTicketId. If no ticket was
        // created, the submit failed — clear the pending state so the modal doesn't hang (the error
        // toast already showed and the text stays for a retry).
        if (supportLogic.values.lastSubmittedTicketId === ticketIdBefore) {
            submitInFlightRef.current = false
            setPendingTicketSubmission(false)
        }
    }

    function handleSupportModalCancel(): void {
        // The in-flight request cannot be aborted, so closing now would re-arm the submit
        // controls and allow a duplicate ticket
        if (submitInFlightRef.current) {
            return
        }
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
                    <LemonButton
                        type="secondary"
                        onClick={handleSupportModalCancel}
                        disabledReason={pendingTicketSubmission ? 'Submitting your ticket…' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        data-attr="submit"
                        onClick={() => void handleSupportFormSubmit()}
                        loading={pendingTicketSubmission}
                        disabledReason={hasSubmittedTicket ? 'Ticket already created' : undefined}
                    >
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
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={showTicketPreviewOrOpenModal}
                                disabledReason={hasSubmittedTicket ? 'Ticket already created' : undefined}
                            >
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
                        <LemonButton
                            type="primary"
                            size="small"
                            onClick={openSupportModalWithPrefill}
                            disabledReason={hasSubmittedTicket ? 'Ticket already created' : undefined}
                        >
                            Review support ticket
                        </LemonButton>
                    </div>
                </div>
            </MessageTemplate>
            {supportModal}
        </>
    )
}
