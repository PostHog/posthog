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
    onSendMessage: (content: string) => void
    onLoadOlderMessages?: () => void
    header?: React.ReactNode
    minHeight?: string
    maxHeight?: string
    compact?: boolean
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
    compact = false,
}: ChatViewProps): JSX.Element {
    const listMinHeight = minHeight ?? (compact ? '300px' : '400px')
    const listMaxHeight = maxHeight ?? (compact ? '400px' : '600px')

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
            />
            <div className="border-t pt-3">
                <MessageInput onSendMessage={onSendMessage} messageSending={messageSending} multiline={true} />
            </div>
        </LemonCard>
    )
}
