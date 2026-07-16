import type { Meta, StoryObj } from '@storybook/react'
import { CheckIcon } from 'lucide-react'
import * as React from 'react'

import { Button } from '../button'
import { ChatMarker, ChatMarkerContent, ChatMarkerIcon } from './chat-marker'
import {
    ChatReasoning,
    ChatReasoningContent,
    ChatReasoningLabel,
    ChatReasoningStep,
    ChatReasoningTrigger,
} from './chat-reasoning'

const meta: Meta<typeof ChatReasoning> = {
    title: 'Primitives/Chat/ChatReasoning',
    component: ChatReasoning,
    tags: ['autodocs'],
}

export default meta
type Story = StoryObj<typeof meta>

const STEPS = [
    'Reading the request and locating the jwt.verify call inside the auth middleware.',
    'The verify call sets no algorithms allowlist, so a token signed with "none" could be accepted.',
    'Tracing where the signing secret is loaded from and confirming it is never logged.',
    'Planning to pin the algorithm to HS256 and validate the issuer and audience claims.',
    'Scanning the existing tests around the middleware so the fix stays covered.',
    'Drafting the patch with a regression test that rejects tampered and unsigned tokens.',
]

const STEP_DELAY_MS = 800

/** Live: the panel is force-open, the label shimmers, and the viewport pins to the newest step. */
export const Thinking: Story = {
    render: () => (
        <div className="w-[420px]">
            <ChatReasoning status="thinking">
                <ChatReasoningTrigger>
                    <ChatReasoningLabel>Thinking…</ChatReasoningLabel>
                </ChatReasoningTrigger>
                <ChatReasoningContent>
                    {STEPS.slice(0, 2).map((step) => (
                        <ChatReasoningStep key={step}>{step}</ChatReasoningStep>
                    ))}
                </ChatReasoningContent>
            </ChatReasoning>
        </div>
    ),
}

/** Done: the row becomes a real toggle. Collapsed is the resting state once the answer arrives. */
export const Done: Story = {
    render: () => (
        <div className="w-[420px]">
            <ChatReasoning status="done">
                <ChatReasoningTrigger>
                    <ChatReasoningLabel>Thought for 5s</ChatReasoningLabel>
                </ChatReasoningTrigger>
                <ChatReasoningContent>
                    {STEPS.map((step) => (
                        <ChatReasoningStep key={step}>{step}</ChatReasoningStep>
                    ))}
                </ChatReasoningContent>
            </ChatReasoning>
        </div>
    ),
}

/**
 * `defaultOpen` expands a finished stream — for e.g. auto-expanding the turn the reader jumped to.
 * Past the height cap the viewport scrolls and the edge fades track the scroll position.
 */
export const DoneExpanded: Story = {
    render: () => (
        <div className="w-[420px]">
            <ChatReasoning status="done" defaultOpen>
                <ChatReasoningTrigger>
                    <ChatReasoningLabel>Thought for 5s</ChatReasoningLabel>
                </ChatReasoningTrigger>
                <ChatReasoningContent>
                    {STEPS.map((step) => (
                        <ChatReasoningStep key={step}>{step}</ChatReasoningStep>
                    ))}
                </ChatReasoningContent>
            </ChatReasoning>
        </div>
    ),
}

/** A short stream sits under the cap, so it renders with no fades and no scrollbar. */
export const SingleStep: Story = {
    render: () => (
        <div className="w-[420px]">
            <ChatReasoning status="done" defaultOpen>
                <ChatReasoningTrigger>
                    <ChatReasoningLabel>Thought for 1s</ChatReasoningLabel>
                </ChatReasoningTrigger>
                <ChatReasoningContent>
                    <ChatReasoningStep>Checked the cached schema; nothing to re-fetch.</ChatReasoningStep>
                </ChatReasoningContent>
            </ChatReasoning>
        </div>
    ),
}

/** Override the 11.25rem height cap per surface (a wide panel can afford more). */
export const TallerCap: Story = {
    render: () => (
        <div className="w-[420px]">
            <ChatReasoning status="done" defaultOpen>
                <ChatReasoningTrigger>
                    <ChatReasoningLabel>Thought for 5s</ChatReasoningLabel>
                </ChatReasoningTrigger>
                <ChatReasoningContent className="[--quill-chat-reasoning-max-height:20rem]">
                    {STEPS.map((step) => (
                        <ChatReasoningStep key={step}>{step}</ChatReasoningStep>
                    ))}
                </ChatReasoningContent>
            </ChatReasoning>
        </div>
    ),
}

function LiveReasoning(): React.ReactElement {
    const [runId, setRunId] = React.useState(0)
    const [revealed, setRevealed] = React.useState(0)

    React.useEffect(() => {
        const timers = STEPS.map((_, index) => setTimeout(() => setRevealed(index + 1), STEP_DELAY_MS * (index + 1)))
        return () => timers.forEach(clearTimeout)
    }, [runId])

    const done = revealed === STEPS.length
    const seconds = Math.round((STEPS.length * STEP_DELAY_MS) / 1000)

    return (
        <div className="flex w-[420px] flex-col gap-4">
            <ChatReasoning status={done ? 'done' : 'thinking'} key={runId}>
                <ChatReasoningTrigger>
                    <ChatReasoningLabel>{done ? `Thought for ${seconds}s` : 'Thinking…'}</ChatReasoningLabel>
                </ChatReasoningTrigger>
                <ChatReasoningContent>
                    {STEPS.slice(0, revealed).map((step) => (
                        <ChatReasoningStep key={step}>{step}</ChatReasoningStep>
                    ))}
                </ChatReasoningContent>
            </ChatReasoning>
            <Button
                variant="outline"
                size="sm"
                className="self-start"
                onClick={() => {
                    setRevealed(0)
                    setRunId((id) => id + 1)
                }}
            >
                Replay
            </Button>
        </div>
    )
}

/**
 * The whole arc: steps stream in bottom-anchored, then `status="done"` collapses the panel to its
 * summary. The app owns the timing and the label copy; the primitive owns the reveal and collapse.
 */
export const Live: Story = {
    render: () => <LiveReasoning />,
}

/** In a turn: reasoning above the tool markers it produced. */
export const InConversation: Story = {
    render: () => (
        <div className="flex w-[420px] flex-col gap-2">
            <ChatReasoning status="done">
                <ChatReasoningTrigger>
                    <ChatReasoningLabel>Thought for 5s</ChatReasoningLabel>
                </ChatReasoningTrigger>
                <ChatReasoningContent>
                    {STEPS.map((step) => (
                        <ChatReasoningStep key={step}>{step}</ChatReasoningStep>
                    ))}
                </ChatReasoningContent>
            </ChatReasoning>
            <ChatMarker>
                <ChatMarkerIcon>
                    <CheckIcon />
                </ChatMarkerIcon>
                <ChatMarkerContent>Read 2 files · Edited auth/middleware.ts</ChatMarkerContent>
            </ChatMarker>
        </div>
    ),
}
