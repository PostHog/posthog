import { useEffect, useRef, useState } from 'react'

import { LemonButton, LemonCard, LemonInput, Spinner } from '@posthog/lemon-ui'

import type { CommentType } from '~/types'

import type { Ticket } from '../../types'
import { Message } from './Message'

export interface ChatViewProps {
    messages: CommentType[]
    messagesLoading: boolean
    messageSending: boolean
    hasMoreMessages: boolean
    olderMessagesLoading: boolean
    ticket?: Ticket
    onSendMessage: (content: string) => void
    onLoadOlderMessages: () => void
}

export function ChatView({
    messages,
    messagesLoading,
    messageSending,
    hasMoreMessages,
    olderMessagesLoading,
    ticket,
    onSendMessage,
    onLoadOlderMessages,
}: ChatViewProps): JSX.Element {
    const [messageContent, setMessageContent] = useState('')
    const messagesEndRef = useRef<HTMLDivElement>(null)
    const messagesContainerRef = useRef<HTMLDivElement>(null)

    const scrollToBottom = (): void => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }

    useEffect(() => {
        if (messages.length > 0) {
            scrollToBottom()
        }
    }, [messages.length])

    const handleSendMessage = (): void => {
        if (messageContent.trim()) {
            onSendMessage(messageContent)
            setMessageContent('')
        }
    }

    const handleScroll = (): void => {
        const container = messagesContainerRef.current
        if (!container || olderMessagesLoading || !hasMoreMessages) {
            return
        }

        if (container.scrollTop < 50) {
            onLoadOlderMessages()
        }
    }

    return (
        <LemonCard hoverEffect={false} className="flex flex-col overflow-hidden p-3">
            {/* Chat messages */}
            <div
                ref={messagesContainerRef}
                onScroll={handleScroll}
                className="flex-1 overflow-y-auto p-4 space-y-1.5 min-h-[400px] max-h-[600px]"
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
                    <div className="flex items-center justify-center h-full text-muted-alt text-sm">
                        No messages yet. Start the conversation!
                    </div>
                ) : (
                    <>
                        {messages.map((message: any) => {
                            const authorType = message.item_context?.author_type || 'customer'
                            const isCustomer = authorType === 'customer'

                            let displayName = 'Customer'
                            if (message.created_by) {
                                displayName =
                                    `${message.created_by.first_name} ${message.created_by.last_name}`.trim() ||
                                    message.created_by.email
                            } else if (authorType === 'customer') {
                                displayName =
                                    ticket?.anonymous_traits?.name || ticket?.anonymous_traits?.email || 'Customer'
                            }

                            return (
                                <Message
                                    key={message.id}
                                    message={message}
                                    isCustomer={isCustomer}
                                    displayName={displayName}
                                />
                            )
                        })}
                        <div ref={messagesEndRef} />
                    </>
                )}
            </div>

            {/* Reply input */}
            <div className="border-t p-3">
                <div className="flex gap-2">
                    <LemonInput
                        className="flex-1"
                        placeholder="Type your message..."
                        value={messageContent}
                        onChange={setMessageContent}
                        onPressEnter={handleSendMessage}
                        disabled={messageSending}
                    />
                    <LemonButton
                        type="primary"
                        onClick={handleSendMessage}
                        loading={messageSending}
                        disabled={!messageContent.trim()}
                    >
                        Send
                    </LemonButton>
                </div>
            </div>
        </LemonCard>
    )
}
