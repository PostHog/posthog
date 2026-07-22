import type { Meta, StoryObj } from '@storybook/react'

import * as React from 'react'

import { ChatMarker, ChatMarkerContent } from './chat-marker'
import { ChatStream, ChatStreamLine } from './chat-stream'
import {
    ThreadItem,
    ThreadItemAuthor,
    ThreadItemBody,
    ThreadItemContent,
    ThreadItemGroup,
    ThreadItemGutter,
    ThreadItemHeader,
    ThreadItemTimestamp,
} from './thread-item'
import { Avatar, AvatarFallback } from '../avatar'
import { Button } from '../button'

const meta: Meta<typeof ChatStream> = {
    title: 'Primitives/Chat/ChatStream',
    component: ChatStream,
    tags: ['autodocs'],
}

export default meta
type Story = StoryObj<typeof meta>

const LINES = [
    'Reading the request and locating the jwt.verify call inside the auth middleware.',
    'The verify call sets no algorithms allowlist, so a token signed with "none" could be accepted.',
    'Tracing where the signing secret is loaded from and confirming it is never logged.',
    'Planning to pin the algorithm to HS256 and validate the issuer and audience claims.',
    'Scanning the existing tests around the middleware so the fix stays covered.',
    'Drafting the patch with a regression test that rejects tampered and unsigned tokens.',
]

const LINE_DELAY_MS = 800

/** Pinned: the window follows the newest line, older ones dissolve off the top. */
export const Pinned: Story = {
    render: () => (
        <div className="w-[420px]">
            <ChatStream pinned>
                {LINES.slice(0, 4).map((line) => (
                    <ChatStreamLine key={line}>{line}</ChatStreamLine>
                ))}
            </ChatStream>
        </div>
    ),
}

/** Unpinned: an ordinary scroll area, showing the start, with both edges tracking the scroll. */
export const Unpinned: Story = {
    render: () => (
        <div className="w-[420px]">
            <ChatStream>
                {LINES.map((line) => (
                    <ChatStreamLine key={line}>{line}</ChatStreamLine>
                ))}
            </ChatStream>
        </div>
    ),
}

/** Short output sits under the cap, so it renders with no fades and no scrollbar. */
export const Short: Story = {
    render: () => (
        <div className="w-[420px]">
            <ChatStream pinned>
                <ChatStreamLine>Checked the cached schema; nothing to re-fetch.</ChatStreamLine>
            </ChatStream>
        </div>
    ),
}

/** Override the 11.25rem cap per surface — a wide panel can afford more. */
export const TallerCap: Story = {
    render: () => (
        <div className="w-[420px]">
            <ChatStream className="[--quill-chat-stream-max-height:20rem]">
                {LINES.map((line) => (
                    <ChatStreamLine key={line}>{line}</ChatStreamLine>
                ))}
            </ChatStream>
        </div>
    ),
}

function useStreamed(): { lines: string[]; streaming: boolean; replay: () => void } {
    const [runId, setRunId] = React.useState(0)
    const [count, setCount] = React.useState(0)

    React.useEffect(() => {
        setCount(0)
        const timers = LINES.map((_, index) => setTimeout(() => setCount(index + 1), LINE_DELAY_MS * (index + 1)))
        return () => timers.forEach(clearTimeout)
    }, [runId])

    return { lines: LINES.slice(0, count), streaming: count < LINES.length, replay: () => setRunId((id) => id + 1) }
}

function LiveStream(): React.ReactElement {
    const { lines, streaming, replay } = useStreamed()
    return (
        <div className="flex w-[420px] flex-col gap-4">
            <ChatStream pinned={streaming}>
                {lines.map((line) => (
                    <ChatStreamLine key={line}>{line}</ChatStreamLine>
                ))}
            </ChatStream>
            <Button variant="outline" size="sm" className="self-start" onClick={replay}>
                Replay
            </Button>
        </div>
    )
}

/**
 * The arc: lines arrive and the window follows them, then `pinned` goes false and it hands over to
 * the reader at the start. The app owns the timing; the primitive owns the follow.
 */
export const Live: Story = {
    render: () => <LiveStream />,
}

function ThreadStream(): React.ReactElement {
    const { lines, streaming, replay } = useStreamed()
    return (
        <div className="flex w-[520px] flex-col gap-4">
            <ThreadItemGroup>
                <ThreadItem>
                    <ThreadItemGutter>
                        <Avatar>
                            <AvatarFallback>MX</AvatarFallback>
                        </Avatar>
                    </ThreadItemGutter>
                    <ThreadItemContent>
                        <ThreadItemHeader>
                            <ThreadItemAuthor>Max</ThreadItemAuthor>
                            <ThreadItemTimestamp dateTime="2026-07-16T16:23:00">4:23 PM</ThreadItemTimestamp>
                        </ThreadItemHeader>
                        <ThreadItemBody>
                            <ChatMarker
                                defaultOpen
                                status={streaming ? 'running' : 'done'}
                                body={
                                    <ChatStream pinned={streaming}>
                                        {lines.map((line) => (
                                            <ChatStreamLine key={line}>{line}</ChatStreamLine>
                                        ))}
                                    </ChatStream>
                                }
                            >
                                <ChatMarkerContent>
                                    {streaming ? 'Thinking…' : `Thought for ${LINES.length}s`}
                                </ChatMarkerContent>
                            </ChatMarker>
                        </ThreadItemBody>
                    </ThreadItemContent>
                </ThreadItem>
            </ThreadItemGroup>
            <Button variant="outline" size="sm" className="self-start" onClick={replay}>
                Replay
            </Button>
        </div>
    )
}

/**
 * An agent streaming into a feed row — the composition this exists for. `ChatMarker` brings the
 * summary and the shimmer, its `body` brings the rail, and the stream brings the follow. Nothing
 * here is reasoning-specific: the same shape holds a tailing log or a streaming answer.
 */
export const InThread: Story = {
    render: () => <ThreadStream />,
}
