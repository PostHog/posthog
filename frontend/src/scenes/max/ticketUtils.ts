import { ThreadMessage } from './maxLogic'

export interface TicketSummaryData {
    summary?: string
    discarded?: boolean
    messageIndex: number
}

/**
 * Detects if /ticket was sent as the first message and needs an input form.
 * Returns true when:
 * - First message is /ticket
 * - Last message is the prompt response asking user to describe their issue
 * - No ticket confirmation has been created yet
 */
export function getIsTicketPromptNeeded(threadGrouped: ThreadMessage[], streamingActive: boolean): boolean {
    if (threadGrouped.length < 2 || streamingActive) {
        return false
    }
    const firstMessage = threadGrouped[0]
    const lastMessage = threadGrouped[threadGrouped.length - 1]

    // Check if first message is /ticket and last message is the prompt response
    const isInitialTicketPrompt =
        firstMessage?.type === 'human' &&
        'content' in firstMessage &&
        firstMessage.content === '/ticket' &&
        lastMessage?.type === 'ai' &&
        'content' in lastMessage &&
        lastMessage.content.includes("I'll help you create a support ticket")

    // If a ticket confirmation already exists, don't show the form
    if (isInitialTicketPrompt) {
        const hasConfirmationMessage = threadGrouped.some(
            (msg) =>
                msg?.type === 'ai' && 'content' in msg && msg.content?.includes("I've created a support ticket for you")
        )
        return !hasConfirmationMessage
    }

    return false
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
        if (msg?.type === 'human' && 'content' in msg && msg.content === '/ticket') {
            ticketCommandIndex = i
            break
        }
    }

    // If /ticket is NOT the first human message, and there's an AI response after it
    if (ticketCommandIndex > 0 && ticketCommandIndex < threadGrouped.length - 1) {
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
            return {
                summary: responseMessage.content,
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
