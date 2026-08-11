import { useEffect, useRef, useState } from 'react'

import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { IconArrowDown } from 'lib/lemon-ui/icons'

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
    aiReplyFeedbackDisabledReason?: string
    onSubmitAiReplyFeedback?: (messageId: string, rating: AiReplyFeedbackRating, feedbackText?: string) => void
    /** Non-message timeline entries, placed among the messages by their own timestamp. Opt-in, so a
     * customer-facing view never receives team-only content. */
    extras?: TimelineExtra[]
    currentUserId?: number | null
    /** False when the caller lacks ticket editor access (e.g. viewer-only). */
    canEditTicket?: boolean
    onEditMessage?: (message: ChatMessage) => void
    onDeleteMessage?: (messageId: string) => void
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
    aiReplyFeedbackDisabledReason,
    onSubmitAiReplyFeedback,
    extras = [],
    currentUserId = null,
    canEditTicket = false,
    onEditMessage,
    onDeleteMessage,
}: MessageListProps): JSX.Element {
    const messagesEndRef = useRef<HTMLDivElement>(null)
    const containerRef = useRef<HTMLDivElement>(null)
    // Whether the reader is at (or near) the bottom of the thread. Starts true so
    // the thread opens on its latest message; scrolling up clears it and scrolling
    // back down restores it. Auto-scroll is gated on this so late-arriving content
    // — notably a self-driving agent report, which loads on its own async request
    // separate from the polled messages — never yanks a reader who has scrolled up
    // into history back down to the bottom.
    const pinnedToBottomRef = useRef(true)
    // Latches once the thread has been opened at the bottom, so that initial jump
    // happens exactly once per loaded thread rather than on every content change.
    const openedAtBottomRef = useRef(false)
    // Raised when new tail content lands while the reader has scrolled up into
    // history. Drives the "See new messages" pill so they can drop to the latest
    // on their own terms instead of being yanked down.
    const [newContentBelow, setNewContentBelow] = useState(false)
    // The newest message id, so the effect can tell a real tail append (or a new
    // agent report) from an older-page prepend — "Load older" grows messages.length
    // too, but must never raise the pill.
    const lastMessageId = messages.length > 0 ? messages[messages.length - 1].id : null
    const prevLastMessageIdRef = useRef<string | null>(null)
    const prevExtrasCountRef = useRef(0)

    const scrollToBottom = (behavior: ScrollBehavior = 'smooth'): void => {
        const container = containerRef.current
        if (container) {
            container.scrollTo({ top: container.scrollHeight, behavior })
        }
    }

    const jumpToLatest = (): void => {
        pinnedToBottomRef.current = true
        setNewContentBelow(false)
        scrollToBottom()
    }

    useEffect(() => {
        // No content yet: reset the latch and tail tracking so a freshly loaded
        // thread opens at the bottom again (e.g. after switching tickets).
        if (messages.length === 0 && extras.length === 0) {
            openedAtBottomRef.current = false
            prevLastMessageIdRef.current = null
            prevExtrasCountRef.current = 0
            setNewContentBelow(false)
            return
        }

        const prevLastMessageId = prevLastMessageIdRef.current
        const prevExtrasCount = prevExtrasCountRef.current
        prevLastMessageIdRef.current = lastMessageId
        prevExtrasCountRef.current = extras.length

        // Open at the latest message the first time content lands, instantly.
        if (!openedAtBottomRef.current) {
            openedAtBottomRef.current = true
            pinnedToBottomRef.current = true
            scrollToBottom('instant')
            return
        }

        // Only a tail append (newest message id advanced) or a new extra (agent
        // report) counts as new content below. Prepending older pages changes
        // messages[0], not the last id, so "Load older" never raises the pill.
        const tailGrew = lastMessageId !== prevLastMessageId || extras.length > prevExtrasCount
        if (!tailGrew) {
            return
        }

        // Follow the tail when the reader is already there; otherwise hold their
        // position and raise the pill so they can drop to the latest themselves.
        if (pinnedToBottomRef.current) {
            scrollToBottom()
        } else {
            setNewContentBelow(true)
        }
    }, [lastMessageId, extras.length, messages.length])

    const handleScroll = (): void => {
        const container = containerRef.current
        if (!container) {
            return
        }

        // Track whether the reader is pinned to the bottom. The window is generous
        // so a smooth auto-scroll still in flight keeps counting as pinned.
        pinnedToBottomRef.current = container.scrollHeight - container.scrollTop - container.clientHeight < 120
        // Returning to the bottom (by the pill or by hand) clears the pill.
        if (pinnedToBottomRef.current) {
            setNewContentBelow(false)
        }

        if (olderMessagesLoading || !hasMoreMessages || !onLoadOlderMessages) {
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
            const canModify =
                canEditTicket &&
                !!message.isPrivate &&
                message.authorType === 'human' &&
                !!currentUserId &&
                message.createdBy?.id === currentUserId
            return {
                at: message.createdAt,
                rank: 0,
                element: (
                    <Message
                        key={`${message.id}-${message.version ?? 0}`}
                        message={message}
                        isCustomer={isCustomerView ? !isCustomer : isCustomer}
                        deliveryStatus={deliveryStatusMap.get(message.id)}
                        showAiReplyFeedback={
                            showAiReplyFeedback && message.id === latestAiMessageId && message.authorType === 'AI'
                        }
                        aiReplyFeedbackRating={feedbackByMessageId[message.id] ?? null}
                        aiReplyFeedbackDisabledReason={aiReplyFeedbackDisabledReason}
                        onSubmitAiReplyFeedback={
                            onSubmitAiReplyFeedback
                                ? (rating, feedbackText) => onSubmitAiReplyFeedback(message.id, rating, feedbackText)
                                : undefined
                        }
                        onEdit={canModify && onEditMessage ? () => onEditMessage(message) : undefined}
                        onDelete={canModify && onDeleteMessage ? () => onDeleteMessage(message.id) : undefined}
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
        // The wrapper is the component root, so it keeps the contract the scroll container used to
        // hold: it takes the caller's className and the height bounds, and stays the flex child
        // callers lay out against. Without that, a caller's spacing (e.g. `mb-3`) would land inside
        // the wrapper and stop separating the thread from whatever follows it.
        <div className={`relative flex flex-col flex-1 ${className}`} style={{ minHeight, maxHeight }}>
            <div
                ref={containerRef}
                onScroll={handleScroll}
                data-attr="message-list-scroll"
                className="flex-1 min-h-0 overflow-y-auto space-y-1.5"
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
            {/* Sits over the bottom of the thread, not in the scroll flow, so it stays put as a
                jump-to-latest affordance while the reader is up in history. The strip ignores
                pointer events so only the pill itself is clickable. */}
            {newContentBelow && (
                <div className="absolute inset-x-0 bottom-2 flex justify-center pointer-events-none">
                    <LemonButton
                        type="primary"
                        size="small"
                        icon={<IconArrowDown />}
                        onClick={jumpToLatest}
                        className="pointer-events-auto rounded-full shadow-md"
                    >
                        See new messages
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
