import { JSONContent } from '@tiptap/core'

import { LemonCard } from '@posthog/lemon-ui'

import type { ChatMessage, Ticket } from '../../types'
import { MessageInput } from './MessageInput'
import { MessageList } from './MessageList'

export interface ChatViewProps {
    messages: ChatMessage[]
    messagesLoading: boolean
    messageSending: boolean
    hasMoreMessages?: boolean
    olderMessagesLoading?: boolean
    ticket?: Ticket
    onSendMessage: (content: string, richContent: JSONContent | null, isPrivate: boolean, onSuccess: () => void) => void
    onLoadOlderMessages?: () => void
    header?: React.ReactNode
    minHeight?: string
    maxHeight?: string
    /** Whether to show the "Send as private" option in the message input */
    showPrivateOption?: boolean
    /** Number of team messages that haven't been read by the customer */
    unreadCustomerCount?: number
    /** Whether to show delivery status on team messages */
    showDeliveryStatus?: boolean
}

export function ChatView({
    messages,
    messagesLoading,
    messageSending,
    hasMoreMessages = false,
    olderMessagesLoading = false,
    onSendMessage,
    onLoadOlderMessages,
    header,
    minHeight,
    maxHeight,
    showPrivateOption = false,
    unreadCustomerCount,
    showDeliveryStatus = false,
}: ChatViewProps): JSX.Element {
    const listMinHeight = minHeight ?? '400px'
    const listMaxHeight = maxHeight ?? '600px'

    return (
        <LemonCard hoverEffect={false} className="flex flex-col overflow-hidden p-3">
            {header}
            <MessageList
                messages={messages}
                messagesLoading={messagesLoading}
                hasMoreMessages={hasMoreMessages}
                olderMessagesLoading={olderMessagesLoading}
                onLoadOlderMessages={onLoadOlderMessages}
                emptyMessage="No messages yet. Start the conversation!"
                minHeight={listMinHeight}
                maxHeight={listMaxHeight}
                unreadCustomerCount={unreadCustomerCount}
                showDeliveryStatus={showDeliveryStatus}
            />
            <div className="border-t pt-3">
                <MessageInput
                    onSendMessage={onSendMessage}
                    messageSending={messageSending}
                    showPrivateOption={showPrivateOption}
                />
            </div>
        </LemonCard>
    )
}
