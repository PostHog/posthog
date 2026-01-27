import { useEffect, useRef } from 'react'

import { Spinner } from '@posthog/lemon-ui'

import type { ChatMessage } from '../../types'
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
        if (messages.length > 0) {
            scrollToBottom()
        }
    }, [messages.length])

    const handleScroll = (): void => {
        const container = containerRef.current
        if (!container || olderMessagesLoading || !hasMoreMessages || !onLoadOlderMessages) {
            return
        }

        if (container.scrollTop < 50) {
            onLoadOlderMessages()
        }
    }

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
                    {messages.map((message) => {
                        const isCustomer = message.authorType === 'customer'
                        return (
                            <Message
                                key={message.id}
                                message={message}
                                isCustomer={isCustomerView ? !isCustomer : isCustomer}
                            />
                        )
                    })}
                    <div ref={messagesEndRef} />
                </>
            )}
        </div>
    )
}
