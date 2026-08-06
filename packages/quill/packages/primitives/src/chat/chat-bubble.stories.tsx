import type { Meta, StoryObj } from '@storybook/react'

import { ChatBubble, ChatBubbleContent, ChatBubbleGroup, ChatBubbleReactions } from './chat-bubble'

const meta = {
    title: 'Primitives/Chat/ChatBubble',
    component: ChatBubble,
    tags: ['autodocs'],
    argTypes: {
        variant: {
            control: 'select',
            options: ['default', 'secondary', 'muted', 'tinted', 'outline', 'ghost', 'destructive'],
        },
        align: { control: 'inline-radio', options: ['start', 'end'] },
    },
} satisfies Meta<typeof ChatBubble>

export default meta
type Story = StoryObj<typeof meta>

const VARIANTS = [
    { variant: 'default', description: 'A strong primary bubble, usually for the current user.' },
    { variant: 'secondary', description: 'The standard neutral bubble for conversation content.' },
    { variant: 'muted', description: 'A lower-emphasis bubble for quiet supporting content.' },
    { variant: 'tinted', description: 'A subtle primary-tinted bubble.' },
    { variant: 'outline', description: 'A bordered bubble for secondary or rich content.' },
    { variant: 'ghost', description: 'Unframed content for assistant text or rich content.' },
    { variant: 'destructive', description: 'A destructive bubble for error or failed actions.' },
] as const

/** Every variant. Fills are generic/neutral — restyle per product in `chat-bubble.css`. */
export const Variants = {
    render: () => (
        <div className="flex w-[420px] flex-col gap-3">
            {VARIANTS.map(({ variant, description }) => (
                <ChatBubble key={variant} variant={variant}>
                    <ChatBubbleContent>{description}</ChatBubbleContent>
                </ChatBubble>
            ))}
        </div>
    ),
} satisfies Story

/** start vs end alignment, as used for assistant (start) vs user (end). */
export const Alignment = {
    render: () => (
        <div className="flex w-[420px] flex-col gap-3">
            <ChatBubble align="start" variant="muted">
                <ChatBubbleContent>Assistant, start-aligned.</ChatBubbleContent>
            </ChatBubble>
            <ChatBubble align="end" variant="default">
                <ChatBubbleContent>User, end-aligned.</ChatBubbleContent>
            </ChatBubble>
        </div>
    ),
} satisfies Story

/** Consecutive bubbles in a group, with a reaction overlay. */
export const GroupWithReactions = {
    render: () => (
        <div className="w-[420px]">
            <ChatBubbleGroup>
                <ChatBubble variant="muted">
                    <ChatBubbleContent>First message in the group.</ChatBubbleContent>
                </ChatBubble>
                <ChatBubble variant="muted">
                    <ChatBubbleContent>Second message — reactions sit on the surface.</ChatBubbleContent>
                    <ChatBubbleReactions>
                        <span>👍</span>
                        <span>🎉</span>
                    </ChatBubbleReactions>
                </ChatBubble>
            </ChatBubbleGroup>
        </div>
    ),
} satisfies Story
