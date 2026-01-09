import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useCallback, useEffect, useState } from 'react'

import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { SupportForm } from 'lib/components/Support/SupportForm'
import { supportLogic } from 'lib/components/Support/supportLogic'

import { maxThreadLogic } from './maxThreadLogic'

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
}

/**
 * In-chat support ticket form for the /ticket command.
 * - If `summary` is provided: shows "Create support ticket" button with pre-filled summary
 * - If no `summary`: shows input field for user to describe their issue
 */
export function TicketPrompt({ conversationId, traceId, summary, initialText }: TicketPromptProps): JSX.Element {
    const [issueText, setIssueText] = useState(initialText ?? '')
    const [isSubmitting, setIsSubmitting] = useState(false)
    const [isSupportModalOpen, setIsSupportModalOpen] = useState(false)

    const { sendSupportRequest, lastSubmittedTicketId } = useValues(supportLogic)
    const { resetSendSupportRequest, setSendSupportRequestValue, submitSendSupportRequest, closeSupportForm } =
        useActions(supportLogic)
    const { appendMessageToConversation } = useActions(maxThreadLogic)

    const [pendingTicketSubmission, setPendingTicketSubmission] = useState(false)
    const [ticketIdBeforeSubmission, setTicketIdBeforeSubmission] = useState<string | null>(null)

    const messageContent = summary || issueText

    const handleTicketCreated = useCallback(
        (ticketId: string): void => {
            posthog.capture('posthog_ai_support_ticket_created', {
                $ai_conversation_id: conversationId,
                $ai_session_id: conversationId,
                $ai_trace_id: traceId,
                $ai_support_ticket_id: ticketId,
            })

            // Persist the confirmation message and add it to the thread
            const confirmationMessage = formatConfirmationMessage(ticketId)
            appendMessageToConversation(confirmationMessage)

            setIsSupportModalOpen(false)
            setIsSubmitting(false)
            closeSupportForm()
        },
        [conversationId, traceId, appendMessageToConversation, closeSupportForm]
    )

    useEffect(() => {
        if (pendingTicketSubmission && lastSubmittedTicketId && lastSubmittedTicketId !== ticketIdBeforeSubmission) {
            handleTicketCreated(lastSubmittedTicketId)
            setPendingTicketSubmission(false)
        }
    }, [lastSubmittedTicketId, pendingTicketSubmission, ticketIdBeforeSubmission, handleTicketCreated])

    function appendMetadataToMessage(message: string): string {
        const metadataLines = [`Conversation ID: ${conversationId}`, traceId ? `Trace ID: ${traceId}` : null].filter(
            Boolean
        )
        return message ? `${message}\n\n----\n${metadataLines.join('\n')}` : metadataLines.join('\n')
    }

    function openSupportModal(): void {
        resetSendSupportRequest({
            name: '',
            email: '',
            kind: 'bug',
            target_area: 'max-ai',
            severity_level: 'low',
            message: messageContent,
            tags: ['raised_from_posthog_ai_chat'],
        })
        setIsSupportModalOpen(true)
    }

    function handleSupportFormSubmit(): void {
        setIsSubmitting(true)

        const finalMessage = appendMetadataToMessage(sendSupportRequest.message)
        setSendSupportRequestValue('message', finalMessage)
        setTicketIdBeforeSubmission(lastSubmittedTicketId)
        setPendingTicketSubmission(true)
        submitSendSupportRequest()
    }

    function handleSupportModalCancel(): void {
        setIsSupportModalOpen(false)
        setPendingTicketSubmission(false)
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
                    <LemonButton type="secondary" onClick={handleSupportModalCancel}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        data-attr="submit"
                        onClick={handleSupportFormSubmit}
                        loading={isSubmitting}
                    >
                        Submit
                    </LemonButton>
                </div>
            }
        >
            <SupportForm />
        </LemonModal>
    )

    // With summary: just show the button
    if (summary) {
        return (
            <>
                <div className="flex gap-2 ml-1 mt-1">
                    <LemonButton type="primary" size="small" onClick={openSupportModal}>
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
                    onPressEnter={openSupportModal}
                    fullWidth
                    autoFocus
                />
                <div className="flex gap-2">
                    <LemonButton type="primary" size="small" onClick={openSupportModal} disabled={!issueText.trim()}>
                        Create support ticket
                    </LemonButton>
                </div>
            </div>
            {supportModal}
        </>
    )
}
