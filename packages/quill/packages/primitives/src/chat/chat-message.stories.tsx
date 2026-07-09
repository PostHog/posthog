import type { Meta, StoryObj } from '@storybook/react'
import * as React from 'react'

import { ChatBubble, ChatBubbleContent } from './chat-bubble'
import {
    ChatMessage,
    ChatMessageAvatar,
    ChatMessageContent,
    ChatMessageFooter,
    ChatMessageGroup,
    ChatMessageHeader,
} from './chat-message'

const meta = {
    title: 'Primitives/Chat/ChatMessage',
    component: ChatMessage,
    tags: ['autodocs'],
    argTypes: {
        align: { control: 'inline-radio', options: ['start', 'end'] },
    },
} satisfies Meta<typeof ChatMessage>

export default meta
type Story = StoryObj<typeof meta>

function Avatar({ children }: { children: string }): React.ReactElement {
    return <div className="grid size-7 place-items-center text-[0.625rem] font-medium">{children}</div>
}

/** Assistant (start, ghost bubble, no avatar) vs user (end, filled bubble). */
export const Conversation = {
    render: () => (
        <div className="flex w-[480px] flex-col gap-6">
            <ChatMessage align="start">
                <ChatMessageContent>
                    <ChatBubble variant="ghost">
                        <ChatBubbleContent>
                            Sure — I checked the config and ran the build. Everything passed.
                        </ChatBubbleContent>
                    </ChatBubble>
                </ChatMessageContent>
            </ChatMessage>

            <ChatMessage align="end">
                <ChatMessageContent>
                    <ChatBubble align="end" variant="default">
                        <ChatBubbleContent>Thanks! Can you also run the tests?</ChatBubbleContent>
                    </ChatBubble>
                </ChatMessageContent>
            </ChatMessage>
        </div>
    ),
} satisfies Story

/** With optional avatar, header (name), and footer (timestamp/actions). */
export const WithAvatarHeaderFooter = {
    render: () => (
        <div className="w-[480px]">
            <ChatMessage align="start">
                <ChatMessageAvatar>
                    <Avatar>AI</Avatar>
                </ChatMessageAvatar>
                <ChatMessageContent>
                    <ChatMessageHeader>Assistant</ChatMessageHeader>
                    <ChatBubble variant="muted">
                        <ChatBubbleContent>Avatar anchors to the bottom of the message.</ChatBubbleContent>
                    </ChatBubble>
                    <ChatMessageFooter>just now</ChatMessageFooter>
                </ChatMessageContent>
            </ChatMessage>
        </div>
    ),
} satisfies Story

/** Consecutive messages from the same author collapse spacing via MessageGroup. */
export const Group = {
    render: () => (
        <div className="w-[480px]">
            <ChatMessageGroup>
                <ChatMessage align="end">
                    <ChatMessageContent>
                        <ChatBubble align="end">
                            <ChatBubbleContent>One.</ChatBubbleContent>
                        </ChatBubble>
                    </ChatMessageContent>
                </ChatMessage>
                <ChatMessage align="end">
                    <ChatMessageContent>
                        <ChatBubble align="end">
                            <ChatBubbleContent>Two, tighter spacing.</ChatBubbleContent>
                        </ChatBubble>
                    </ChatMessageContent>
                </ChatMessage>
            </ChatMessageGroup>
        </div>
    ),
} satisfies Story
