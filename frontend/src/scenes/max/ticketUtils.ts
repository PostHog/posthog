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
            (msg) =>
                msg?.type === 'ai' && 'content' in msg && msg.content?.includes("I've created a support ticket for you")
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
            !responseMessage.content.includes("I'll help you create a support ticket")
        ) {
            // Check if user continued the conversation (sent another message after the summary)
            // or if a ticket was already created
            const messagesAfterSummary = threadGrouped.slice(ticketCommandIndex + 2)
            const userContinuedConversation = messagesAfterSummary.some((msg) => msg?.type === 'human')
            const hasConfirmationMessage = messagesAfterSummary.some(
                (msg) =>
                    msg?.type === 'ai' &&
                    'content' in msg &&
                    msg.content?.includes("I've created a support ticket for you")
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
 * Checks if a message is a ticket confirmation message.
 */
export function isTicketConfirmationMessage(message: ThreadMessage): boolean {
    return (
        message.type !== 'human' &&
        'content' in message &&
        typeof message.content === 'string' &&
        message.content.includes("I've created a support ticket for you")
    )
}
