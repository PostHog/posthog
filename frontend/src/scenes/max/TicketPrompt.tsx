import { useActions, useValues } from 'kea'
import { useRef, useState } from 'react'

import { LemonButton, LemonInput, LemonModal, lemonToast } from '@posthog/lemon-ui'

import { SupportForm } from 'lib/components/Support/SupportForm'
import { SupportTicketTargetArea, supportLogic } from 'lib/components/Support/supportLogic'
import { userLogic } from 'scenes/userLogic'

import { maxThreadLogic } from './maxThreadLogic'
import { appendTicketMetadata, composeTicketBody } from './ticketUtils'

function formatConfirmationMessage(ticketId: string): string {
    return `I've created a support ticket for you.\nYour ticket ID is #${ticketId}.\nOur support team will get back to you soon!`
}

interface TicketPromptProps {
    conversationId: string
    traceId: string | null
    /** If provided, skip the input step and use this summary directly */
    summary?: string
    /** If provided, pre-populate the input field with this text */
    initialText?: string
    /** Target area inferred from the conversation; falls back to product analytics when absent */
    targetArea?: SupportTicketTargetArea | null
}

/**
 * In-chat support ticket form for the /ticket command.
 * - If `summary` is provided: shows a "Create support ticket" button; the modal attaches the AI
 *   summary as context and offers an optional "anything to add" note
 * - If no `summary`: shows input field for user to describe their issue
 */
export function TicketPrompt({
    conversationId,
    traceId,
    summary,
    initialText,
    targetArea,
}: TicketPromptProps): JSX.Element {
    const [issueText, setIssueText] = useState(initialText ?? '')
    const [isSubmitting, setIsSubmitting] = useState(false)
    const [hasSubmitted, setHasSubmitted] = useState(false)
    const [isSupportModalOpen, setIsSupportModalOpen] = useState(false)

    const { sendSupportRequest, conversationsFlagEnabled } = useValues(supportLogic)
    const { resetSendSupportRequest, closeSupportForm } = useActions(supportLogic)
    const { appendMessageToConversation } = useActions(maxThreadLogic)
    const { user } = useValues(userLogic)

    const submitInFlightRef = useRef(false)

    function handleTicketCreated(ticketId: string): void {
        // Persist the confirmation message and add it to the thread
        const confirmationMessage = formatConfirmationMessage(ticketId)
        appendMessageToConversation(confirmationMessage)

        submitInFlightRef.current = false
        setHasSubmitted(true)
        setIsSupportModalOpen(false)
        setIsSubmitting(false)
        closeSupportForm()
    }

    function openSupportModal(): void {
        if (hasSubmitted) {
            return
        }
        resetSendSupportRequest({
            name: '',
            email: '',
            kind: 'bug',
            target_area: targetArea ?? 'analytics',
            severity_level: 'low',
            message: summary ? '' : issueText,
            tags: ['raised_from_posthog_ai_chat'],
            ai_conversation_id: conversationId,
            ai_trace_id: traceId,
        })
        setIsSupportModalOpen(true)
    }

    async function handleSupportFormSubmit(): Promise<void> {
        if (submitInFlightRef.current || hasSubmitted) {
            return
        }

        const body = composeTicketBody({ note: sendSupportRequest.message, summary })
        const finalMessage = appendTicketMetadata(body, { conversationId, traceId })
        if (!finalMessage) {
            lemonToast.error('Please add a description before creating a ticket.')
            return
        }
        // The Zendesk form variant requires the triage fields the kea-forms validator would have
        // enforced before this direct submit
        if (
            !conversationsFlagEnabled &&
            (!sendSupportRequest.kind || !sendSupportRequest.target_area || !sendSupportRequest.severity_level)
        ) {
            lemonToast.error('Please choose a message type, topic, and severity level.')
            return
        }

        submitInFlightRef.current = true
        setIsSubmitting(true)
        const ticketIdBefore = supportLogic.values.lastSubmittedTicketId
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
        const ticketIdAfter = supportLogic.values.lastSubmittedTicketId
        if (ticketIdAfter && ticketIdAfter !== ticketIdBefore) {
            handleTicketCreated(ticketIdAfter)
        } else {
            // Submit failed (the error toast already showed) — allow a retry with the note untouched
            submitInFlightRef.current = false
            setIsSubmitting(false)
        }
    }

    function handleSupportModalCancel(): void {
        // The in-flight request cannot be aborted, so closing now would re-arm the submit
        // controls and allow a duplicate ticket
        if (submitInFlightRef.current) {
            return
        }
        setIsSupportModalOpen(false)
        setIsSubmitting(false)
        closeSupportForm()
    }

    const supportModal = (
        <LemonModal
            isOpen={isSupportModalOpen}
            onClose={handleSupportModalCancel}
            title="Create support ticket"
            footer={
                <div className="flex items-center gap-2">
                    <LemonButton
                        type="secondary"
                        onClick={handleSupportModalCancel}
                        disabledReason={isSubmitting ? 'Submitting your ticket…' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        data-attr="submit"
                        onClick={() => void handleSupportFormSubmit()}
                        loading={isSubmitting}
                        disabledReason={hasSubmitted ? 'Ticket already created' : undefined}
                    >
                        Submit
                    </LemonButton>
                </div>
            }
        >
            {summary && (
                <div className="flex flex-col gap-1 mb-3">
                    <p className="m-0 font-medium">PostHog AI's analysis</p>
                    <p className="m-0 text-xs text-secondary">This is attached to your ticket for our support team.</p>
                    <div className="max-h-40 overflow-y-auto p-2 border border-border rounded bg-bg-light text-sm whitespace-pre-wrap">
                        {summary}
                    </div>
                </div>
            )}
            <SupportForm
                messageLabel={summary ? 'Anything to add? (optional)' : undefined}
                messagePlaceholder={
                    summary ? 'Add anything that would help our support team understand your issue' : undefined
                }
            />
        </LemonModal>
    )

    // With summary: just show the button
    if (summary) {
        return (
            <>
                <div className="flex gap-2 ml-1 mt-1">
                    <LemonButton
                        type="primary"
                        size="small"
                        onClick={openSupportModal}
                        disabledReason={hasSubmitted ? 'Ticket already created' : undefined}
                    >
                        Create support ticket
                    </LemonButton>
                </div>
                {supportModal}
            </>
        )
    }

    // Without summary: show input field
    return (
        <>
            <div className="w-full flex flex-col gap-2 p-3 border border-border rounded-lg bg-bg-light">
                <p className="m-0 font-medium">Describe your issue</p>
                <LemonInput
                    placeholder="What do you need help with?"
                    value={issueText}
                    onChange={setIssueText}
                    onPressEnter={() => {
                        if (issueText.trim()) {
                            openSupportModal()
                        }
                    }}
                    fullWidth
                    autoFocus
                />
                <div className="flex gap-2">
                    <LemonButton
                        type="primary"
                        size="small"
                        onClick={openSupportModal}
                        disabledReason={
                            hasSubmitted
                                ? 'Ticket already created'
                                : !issueText.trim()
                                  ? 'Describe your issue first'
                                  : undefined
                        }
                    >
                        Create support ticket
                    </LemonButton>
                </div>
            </div>
            {supportModal}
        </>
    )
}
