import { useEffect, useRef } from 'react'

import { Spinner } from '@posthog/lemon-ui'

import type { AiReplyFeedbackRating, ChatMessage, MessageDeliveryStatus } from '../../types'
import { Message } from './Message'

export interface MessageListProps {
    messages: ChatMessage[]
    messagesLoading: boolean
    hasMoreMessages?: boolean
    olderMessagesLoading?: boolean
    onLoadOlderMessages?: () => void
    emptyMessage?: string
    className?: string
    minHeight?: string
    maxHeight?: string
    /** When true, flips alignment so customer messages appear on the right (for customer-facing views) */
    isCustomerView?: boolean
    /** Number of team messages that haven't been read by the customer */
    unreadCustomerCount?: number
    /** Whether to show delivery status on team messages */
    showDeliveryStatus?: boolean
    /** ID of the latest AI message eligible for reviewer feedback */
    latestAiMessageId?: string | null
    /** Recorded reviewer feedback keyed by message id */
    feedbackByMessageId?: Record<string, AiReplyFeedbackRating>
    /** Whether AI reply feedback controls are enabled */
    showAiReplyFeedback?: boolean
    onSubmitAiReplyFeedback?: (messageId: string, rating: AiReplyFeedbackRating, feedbackText?: string) => void
    /** Non-message timeline entries, placed among the messages by their own timestamp. Opt-in, so a
     * customer-facing view never receives team-only content. */
    extras?: TimelineExtra[]
}

/** A non-message entry in the thread, e.g. an agent's findings. `at` is what orders it among the
 * messages; `element` carries its own React key. */
export interface TimelineExtra {
    at: string
    element: JSX.Element
}

export function MessageList({
    messages,
    messagesLoading,
    hasMoreMessages = false,
    olderMessagesLoading = false,
    onLoadOlderMessages,
    emptyMessage = 'No messages yet.',
    className = '',
    minHeight = '300px',
    maxHeight = '400px',
    isCustomerView = false,
    unreadCustomerCount = 0,
    showDeliveryStatus = false,
    latestAiMessageId = null,
    feedbackByMessageId = {},
    showAiReplyFeedback = false,
    onSubmitAiReplyFeedback,
    extras = [],
}: MessageListProps): JSX.Element {
    const messagesEndRef = useRef<HTMLDivElement>(null)
    const containerRef = useRef<HTMLDivElement>(null)

    const scrollToBottom = (): void => {
        if (containerRef.current && messagesEndRef.current) {
            containerRef.current.scrollTo({
                top: containerRef.current.scrollHeight,
                behavior: 'smooth',
            })
        }
    }

    useEffect(() => {
        if (messages.length > 0 || extras.length > 0) {
            scrollToBottom()
        }
        // Extras land in the same stream, so one arriving has to scroll like a message does.
    }, [messages.length, extras.length])

    const handleScroll = (): void => {
        const container = containerRef.current
        if (!container || olderMessagesLoading || !hasMoreMessages || !onLoadOlderMessages) {
            return
        }

        if (container.scrollTop < 50) {
            onLoadOlderMessages()
        }
    }

    // Compute delivery status for team messages (non-customer, non-private messages)
    // The last unreadCustomerCount team messages are "sent", the rest are "read"
    const getDeliveryStatusMap = (): Map<string, MessageDeliveryStatus> => {
        if (!showDeliveryStatus) {
            return new Map()
        }

        const statusMap = new Map<string, MessageDeliveryStatus>()
        const teamMessages = messages.filter((m) => m.authorType !== 'customer' && !m.isPrivate)

        let unreadRemaining = unreadCustomerCount
        for (let i = teamMessages.length - 1; i >= 0; i--) {
            const msg = teamMessages[i]
            if (unreadRemaining > 0) {
                statusMap.set(msg.id, 'sent')
                unreadRemaining--
            } else {
                statusMap.set(msg.id, 'read')
            }
        }

        return statusMap
    }

    const deliveryStatusMap = getDeliveryStatusMap()

    // Messages and extras share one chronological stream, so an agent's findings sit at the point in
    // the conversation they arrived rather than always at the bottom. Ties keep messages first, and
    // the original order within each kind, so a same-second reply never reshuffles.
    const timeline: JSX.Element[] = [
        ...messages.map((message) => {
            const isCustomer = message.authorType === 'customer'
            return {
                at: message.createdAt,
                rank: 0,
                element: (
                    <Message
                        key={message.id}
                        message={message}
                        isCustomer={isCustomerView ? !isCustomer : isCustomer}
                        deliveryStatus={deliveryStatusMap.get(message.id)}
                        showAiReplyFeedback={
                            showAiReplyFeedback && message.id === latestAiMessageId && message.authorType === 'AI'
                        }
                        aiReplyFeedbackRating={feedbackByMessageId[message.id] ?? null}
                        onSubmitAiReplyFeedback={
                            onSubmitAiReplyFeedback
                                ? (rating, feedbackText) => onSubmitAiReplyFeedback(message.id, rating, feedbackText)
                                : undefined
                        }
                    />
                ),
            }
        }),
        ...extras.map((extra) => ({ at: extra.at, rank: 1, element: extra.element })),
    ]
        // Array.prototype.sort is stable, so equal (time, rank) pairs keep the order they were
        // concatenated in; only the message-before-extra tiebreak needs stating.
        .sort((a, b) => new Date(a.at).getTime() - new Date(b.at).getTime() || a.rank - b.rank)
        .map(({ element }) => element)

    return (
        <div
            ref={containerRef}
            onScroll={handleScroll}
            className={`flex-1 overflow-y-auto space-y-1.5 ${className}`}
            style={{ minHeight, maxHeight }}
        >
            {olderMessagesLoading && (
                <div className="flex items-center justify-center py-2">
                    <Spinner className="text-sm" />
                </div>
            )}
            {messagesLoading && messages.length === 0 ? (
                <div className="flex items-center justify-center h-full">
                    <Spinner />
                </div>
            ) : messages.length === 0 ? (
                <div className="flex items-center justify-center h-full text-muted-alt text-sm">{emptyMessage}</div>
            ) : (
                <>
                    {timeline}
                    <div ref={messagesEndRef} />
                </>
            )}
        </div>
    )
}
