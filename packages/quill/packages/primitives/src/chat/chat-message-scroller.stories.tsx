import type { Meta, StoryObj } from '@storybook/react'

import { CheckIcon, FileIcon, TerminalIcon } from 'lucide-react'
import * as React from 'react'

import { ChatBubble, ChatBubbleContent } from './chat-bubble'
import { ChatMarker, ChatMarkerContent, ChatMarkerIcon } from './chat-marker'
import { ChatMessage, ChatMessageContent } from './chat-message'
import {
    ChatMessageScroller,
    ChatMessageScrollerButton,
    ChatMessageScrollerContent,
    ChatMessageScrollerItem,
    ChatMessageScrollerProvider,
    ChatMessageScrollerViewport,
} from './chat-message-scroller'
import { Spinner } from '../spinner'

const meta = {
    title: 'Primitives/Chat/ChatMessageScroller',
    component: ChatMessageScroller,
    tags: ['autodocs'],
    parameters: { layout: 'fullscreen' },
} satisfies Meta<typeof ChatMessageScroller>

export default meta
type Story = StoryObj<typeof meta>

/** A single user→assistant exchange, anchored on the user message. */
function Turn({ index, withTools = false }: { index: number; withTools?: boolean }): React.ReactElement {
    return (
        <>
            <ChatMessageScrollerItem messageId={`u-${index}`} scrollAnchor>
                <ChatMessage align="end">
                    <ChatMessageContent>
                        <ChatBubble variant="muted" align="end">
                            <ChatBubbleContent>Turn {index}: can you check the file and run the build?</ChatBubbleContent>
                        </ChatBubble>
                    </ChatMessageContent>
                </ChatMessage>
            </ChatMessageScrollerItem>

            <ChatMessageScrollerItem messageId={`a-${index}`}>
                <ChatMessage align="start">
                    <ChatMessageContent>
                        <ChatBubble variant="ghost">
                            <ChatBubbleContent>
                                Sure — here's what I found. The config looked fine, so I ran the build and it passed.
                            </ChatBubbleContent>
                        </ChatBubble>
                        {withTools && (
                            <ChatMarker
                                defaultOpen={false}
                                body={
                                    <>
                                        <ChatMarker>
                                            <ChatMarkerIcon>
                                                <FileIcon />
                                            </ChatMarkerIcon>
                                            <ChatMarkerContent>Read vite.config.ts</ChatMarkerContent>
                                        </ChatMarker>
                                        <ChatMarker>
                                            <ChatMarkerIcon>
                                                <TerminalIcon />
                                            </ChatMarkerIcon>
                                            <ChatMarkerContent>Ran pnpm build</ChatMarkerContent>
                                        </ChatMarker>
                                    </>
                                }
                            >
                                <ChatMarkerIcon>
                                    <CheckIcon />
                                </ChatMarkerIcon>
                                <ChatMarkerContent>Read 1 file · Ran 1 command</ChatMarkerContent>
                            </ChatMarker>
                        )}
                    </ChatMessageContent>
                </ChatMessage>
            </ChatMessageScrollerItem>
        </>
    )
}

function Frame({ children }: { children: React.ReactNode }): React.ReactElement {
    return (
        <div className="mx-auto h-[600px] w-full max-w-[680px] p-4">
            <ChatMessageScrollerProvider autoScroll defaultScrollPosition="end" scrollPreviousItemPeek={64}>
                <ChatMessageScroller>
                    <ChatMessageScrollerViewport>
                        <ChatMessageScrollerContent className="px-2 py-4">{children}</ChatMessageScrollerContent>
                    </ChatMessageScrollerViewport>
                    <ChatMessageScrollerButton />
                </ChatMessageScroller>
            </ChatMessageScrollerProvider>
        </div>
    )
}

/** The full thread composition: messages, ghost/filled bubbles, and a collapsible tool-group marker. */
export const Default = {
    render: () => (
        <Frame>
            {Array.from({ length: 8 }, (_, i) => (
                <Turn key={i} index={i + 1} withTools={i % 2 === 0} />
            ))}
            <ChatMessageScrollerItem messageId="a-live">
                <ChatMessage align="start">
                    <ChatMessageContent>
                        <ChatMarker>
                            <ChatMarkerIcon>
                                <Spinner />
                            </ChatMarkerIcon>
                            <ChatMarkerContent className="shimmer">Reading large-file.ts…</ChatMarkerContent>
                        </ChatMarker>
                    </ChatMessageContent>
                </ChatMessage>
            </ChatMessageScrollerItem>
        </Frame>
    ),
} satisfies Story

/**
 * Stress: 1000 turns, non-virtualized. Proves the `content-visibility: auto` thesis — every row
 * is in the DOM, but off-screen rows skip layout/paint. Scroll should stay smooth.
 */
export const Stress1000Turns = {
    name: 'Stress · 1000 turns',
    render: () => (
        <Frame>
            {Array.from({ length: 1000 }, (_, i) => (
                <Turn key={i} index={i + 1} withTools={i % 3 === 0} />
            ))}
        </Frame>
    ),
} satisfies Story
