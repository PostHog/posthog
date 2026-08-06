import { ThreadMessage } from './maxLogic'

export interface TicketSummaryData {
    summary?: string
    discarded?: boolean
    messageIndex: number
}

export interface TicketPromptData {
    needed: boolean
    initialText?: string
}

const TICKET_CONFIRMATION_LEAD = "I've created a support ticket for you"

/**
 * Builds the confirmation message shown once a ticket is created. The target response time is left
 * out when the plan has none, so a customer is never promised a reply their plan doesn't cover.
 */
export function formatTicketConfirmationMessage(ticketId: string, responseTime: string | null): string {
    const closingLine = responseTime
        ? `Our support team aims to get back to you within ${responseTime}.`
        : 'Our support team will get back to you soon!'
    return `${TICKET_CONFIRMATION_LEAD}.\nYour ticket ID is #${ticketId}.\n${closingLine}`
}

/**
 * Extracts the text after "/ticket " from a message, if any.
 */
function extractTicketText(content: string): string | undefined {
    if (content.startsWith('/ticket ')) {
        const text = content.slice('/ticket '.length).trim()
        return text || undefined
    }
    return undefined
}

/**
 * Detects if /ticket was sent as the first message and needs an input form.
 * Returns:
 * - { needed: true, initialText } when ticket form should be shown
 * - { needed: false } otherwise
 */
export function getTicketPromptData(threadGrouped: ThreadMessage[], streamingActive: boolean): TicketPromptData {
    if (threadGrouped.length < 2 || streamingActive) {
        return { needed: false }
    }
    const firstMessage = threadGrouped[0]
    const lastMessage = threadGrouped[threadGrouped.length - 1]

    // Check if first message is /ticket and last message is the prompt response
    const isInitialTicketPrompt =
        firstMessage?.type === 'human' &&
        'content' in firstMessage &&
        firstMessage.content.startsWith('/ticket') &&
        lastMessage?.type === 'ai' &&
        'content' in lastMessage &&
        lastMessage.content.includes("I'll help you create a support ticket")

    // If a ticket confirmation already exists, don't show the form
    if (isInitialTicketPrompt) {
        const hasConfirmationMessage = threadGrouped.some(
            (msg) => msg?.type === 'ai' && 'content' in msg && msg.content?.includes(TICKET_CONFIRMATION_LEAD)
        )
        if (!hasConfirmationMessage) {
            const initialText =
                'content' in firstMessage ? extractTicketText(firstMessage.content as string) : undefined
            return { needed: true, initialText }
        }
    }

    return { needed: false }
}

/**
 * Detects if /ticket was sent with an existing conversation and extracts summary data.
 * Returns:
 * - { summary, messageIndex } when a summary is ready for ticket creation
 * - { discarded: true, messageIndex } when user continued conversation after summary
 * - null when no ticket summary is applicable
 */
export function getTicketSummaryData(
    threadGrouped: ThreadMessage[],
    streamingActive: boolean
): TicketSummaryData | null {
    if (threadGrouped.length < 3 || streamingActive) {
        return null
    }

    // Find the last /ticket command
    let ticketCommandIndex = -1
    for (let i = threadGrouped.length - 1; i >= 0; i--) {
        const msg = threadGrouped[i]
        if (msg?.type === 'human' && 'content' in msg && msg.content.startsWith('/ticket')) {
            ticketCommandIndex = i
            break
        }
    }

    // If /ticket is NOT the first human message, and there's an AI response after it
    if (ticketCommandIndex > 0 && ticketCommandIndex < threadGrouped.length - 1) {
        const ticketCommandMessage = threadGrouped[ticketCommandIndex]
        const responseMessage = threadGrouped[ticketCommandIndex + 1]
        if (
            responseMessage?.type === 'ai' &&
            'content' in responseMessage &&
            responseMessage.content &&
            !responseMessage.content.includes("I'll help you create a support ticket") &&
            !responseMessage.content.includes('is available for customers on paid plans')
        ) {
            // Check if user continued the conversation (sent another message after the summary)
            // or if a ticket was already created
            const messagesAfterSummary = threadGrouped.slice(ticketCommandIndex + 2)
            const userContinuedConversation = messagesAfterSummary.some((msg) => msg?.type === 'human')
            const hasConfirmationMessage = messagesAfterSummary.some(
                (msg) => msg?.type === 'ai' && 'content' in msg && msg.content?.includes(TICKET_CONFIRMATION_LEAD)
            )

            if (hasConfirmationMessage) {
                return null
            }
            if (userContinuedConversation) {
                return {
                    discarded: true,
                    messageIndex: ticketCommandIndex + 1,
                }
            }

            // Extract any user-provided text from the /ticket command
            const userText =
                'content' in ticketCommandMessage
                    ? extractTicketText(ticketCommandMessage.content as string)
                    : undefined

            // Combine user text with AI summary if both exist
            const summary = userText ? `User notes: ${userText}\n\n${responseMessage.content}` : responseMessage.content

            return {
                summary,
                messageIndex: ticketCommandIndex + 1,
            }
        }
    }

    return null
}

/**
 * Builds the ticket body from the user's own note and, when present, PostHog AI's summary.
 * The user's note leads so a human framing is always on top; the AI summary is attached as
 * supporting context. Returns an empty string when there is nothing to send.
 */
export function composeTicketBody({ note, summary }: { note: string; summary?: string }): string {
    const trimmedNote = note.trim()
    if (summary) {
        return trimmedNote ? `${trimmedNote}\n\n----\nPostHog AI's analysis:\n${summary}` : summary
    }
    return trimmedNote
}

/**
 * Appends the conversation and trace identifiers to a ticket body. Returns an empty string when
 * the body is empty, so metadata alone can never be submitted as a ticket.
 */
export function appendTicketMetadata(
    body: string,
    { conversationId, traceId }: { conversationId: string; traceId: string | null }
): string {
    const trimmedBody = body.trim()
    if (!trimmedBody) {
        return ''
    }
    const metadataLines = [`Conversation ID: ${conversationId}`, traceId ? `Trace ID: ${traceId}` : null].filter(
        Boolean
    )
    return `${trimmedBody}\n\n----\n${metadataLines.join('\n')}`
}

/**
 * Checks if a message is a ticket confirmation message.
 */
export function isTicketConfirmationMessage(message: ThreadMessage): boolean {
    return (
        message.type !== 'human' &&
        'content' in message &&
        typeof message.content === 'string' &&
        message.content.includes(TICKET_CONFIRMATION_LEAD)
    )
}
