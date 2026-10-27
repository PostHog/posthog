import { JSONContent } from '@tiptap/core'
import { useEffect, useRef } from 'react'

import {
    ChatBubble,
    ChatBubbleContent,
    ChatMessage,
    ChatMessageContent,
    ChatMessageFooter,
    ChatMessageHeader,
    Skeleton,
    Text,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'

import type { ChatMessage as TicketMessage } from '../../types'
import { SupportMarkdown, SupportRichContentPreview } from '../Editor'

interface QuillTicketMessagesProps {
    messages: TicketMessage[]
    messagesLoading: boolean
}

export function QuillTicketMessages({ messages, messagesLoading }: QuillTicketMessagesProps): JSX.Element {
    const containerRef = useRef<HTMLDivElement>(null)
    const lastMessageId = messages.length > 0 ? messages[messages.length - 1].id : null

    // Opens on the latest message and follows new replies as they land.
    useEffect(() => {
        const container = containerRef.current
        if (container) {
            container.scrollTo({ top: container.scrollHeight })
        }
    }, [lastMessageId])

    if (messagesLoading && messages.length === 0) {
        return (
            <div className="flex flex-col gap-3 py-2">
                <Skeleton className="h-12 w-3/4" />
                <Skeleton className="ms-auto h-12 w-2/3" />
            </div>
        )
    }

    if (messages.length === 0) {
        return (
            <Text size="xs" variant="muted" className="py-6 text-center">
                No messages yet.
            </Text>
        )
    }

    return (
        <div ref={containerRef} className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto py-2">
            {messages.map((message) => {
                const fromCustomer = message.authorType === 'customer'
                const align = fromCustomer ? 'end' : 'start'
                return (
                    <ChatMessage key={message.id} align={align}>
                        <ChatMessageContent className="gap-1">
                            {!fromCustomer && (
                                <ChatMessageHeader>
                                    <Text size="xs" weight="medium" render={<span />}>
                                        {message.authorName}
                                    </Text>
                                </ChatMessageHeader>
                            )}
                            <ChatBubble align={align} variant={fromCustomer ? 'default' : 'muted'}>
                                <ChatBubbleContent>
                                    {/* Every message is untrusted, so remote images become click-to-open links
                                        here as in the team's view. PostHog-hosted images still render inline. */}
                                    {message.richContent ? (
                                        <SupportRichContentPreview
                                            content={message.richContent as JSONContent}
                                            className="text-xs"
                                            fallbackContent={message.content}
                                            fallbackDisableImages={message.fromZendesk}
                                        />
                                    ) : (
                                        <SupportMarkdown className="text-xs" disableImages>
                                            {message.content}
                                        </SupportMarkdown>
                                    )}
                                </ChatBubbleContent>
                            </ChatBubble>
                            <ChatMessageFooter>
                                <Text size="xs" variant="muted" render={<span translate="no" />}>
                                    <TZLabel time={message.createdAt} />
                                </Text>
                            </ChatMessageFooter>
                        </ChatMessageContent>
                    </ChatMessage>
                )
            })}
        </div>
    )
}
