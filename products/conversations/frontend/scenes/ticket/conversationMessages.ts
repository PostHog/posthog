import type { CommentType } from '~/types'

import type { ChatMessage, Ticket } from '../../types'

// Distinct, stable colors used to tag messages by their source ticket when more than one
// ticket's conversation is shown interleaved. Index 0 is always the ticket being viewed.
export const MESSAGE_SOURCE_COLORS = [
    '#3b82f6', // blue
    '#8b5cf6', // violet
    '#ec4899', // pink
    '#f59e0b', // amber
    '#10b981', // emerald
    '#ef4444', // red
    '#14b8a6', // teal
    '#6366f1', // indigo
]

export function sourceColorForIndex(index: number): string {
    return MESSAGE_SOURCE_COLORS[index % MESSAGE_SOURCE_COLORS.length]
}

/** Resolve a display name for a message, preferring the message's own author identity, then the
 * ticket-level requester. Shared so every surface (main thread, merged interleave, merge modal)
 * names authors identically. */
function resolveAuthorName(message: CommentType, ticket: Ticket | null): string {
    const authorType = message.item_context?.author_type || 'customer'
    if (message.created_by) {
        return (
            [message.created_by.first_name, message.created_by.last_name].filter(Boolean).join(' ') ||
            message.created_by.email ||
            'Support'
        )
    }
    if (authorType === 'AI') {
        return 'PostHog Assistant'
    }
    const messageAuthorName =
        message.item_context?.author_name ||
        message.item_context?.author_email ||
        message.item_context?.slack_author_name ||
        message.item_context?.teams_author_name ||
        message.item_context?.teams_author_email ||
        message.item_context?.email_from_name
    if (messageAuthorName) {
        return messageAuthorName
    }
    if (authorType === 'customer') {
        return (
            ticket?.person?.properties?.name ||
            ticket?.person?.properties?.email ||
            ticket?.anonymous_traits?.name ||
            ticket?.anonymous_traits?.email ||
            'Anonymous user'
        )
    }
    return 'Support'
}

/** Map a stored Comment to the ChatMessage shape the chat UI renders. `source` optionally tags the
 * message with the ticket it came from (used when interleaving merged tickets). */
export function commentToChatMessage(
    message: CommentType,
    ticket: Ticket | null,
    source?: { ticketId: string; ticketNumber: number; color: string }
): ChatMessage {
    const authorType = message.item_context?.author_type || 'customer'
    return {
        id: message.id,
        content: message.content || '',
        richContent: message.rich_content,
        authorType: authorType === 'support' ? 'human' : authorType,
        authorName: resolveAuthorName(message, ticket),
        createdBy: message.created_by,
        createdAt: message.created_at,
        isPrivate: message.item_context?.is_private || false,
        emailDeliveryStatus: message.item_context?.email_delivery_status,
        fromZendesk: message.item_context?.from_zendesk === true,
        sourceTicketId: source?.ticketId,
        sourceTicketNumber: source?.ticketNumber,
        sourceColor: source?.color,
    }
}
