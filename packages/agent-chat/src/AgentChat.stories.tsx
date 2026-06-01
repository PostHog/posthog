/**
 * Stories for `<AgentChat />`.
 *
 *  - **Frames** group proves the chat lib has no baked-in chrome —
 *    same content rendered embedded (no frame), inside a rounded
 *    card, and as a fullscreen panel. Hosts wrap it however they
 *    want; the lib just fills its box.
 *  - **Context** group exercises waiting / active / streaming / etc.
 *    against the embedded frame so visual diffs stay isolated to the
 *    transcript engine.
 */

import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'
import { AgentChat } from './AgentChat'
import type { ChatContext } from './context'
import { allSessionStates, weeklyDigest } from './fixtures'
import type { ChatSession, ClientToolHandler, ClientToolRenderCallbacks, Turn } from './types'

const meta: Meta<typeof AgentChat> = {
    title: 'Agent Chat/AgentChat',
    component: AgentChat,
    parameters: {
        layout: 'centered',
    },
    decorators: [
        // Default — embedded, no chrome. Just a sized box so storybook
        // has something to lay the chat into. Hosts (the agent console
        // dock, a floating overlay, a fullscreen panel) supply their
        // own frame — see the `Frame*` stories below for examples.
        (Story) => (
            <div className="h-[640px] w-[360px] bg-background">
                <Story />
            </div>
        ),
    ],
}

export default meta
type Story = StoryObj<typeof AgentChat>

const conciergeListContext: ChatContext = { mode: 'concierge', page: { kind: 'agent-list' } }
const conciergeAgentContext: ChatContext = { mode: 'concierge', page: { kind: 'agent', agent: weeklyDigest } }
const conciergeBundleContext: ChatContext = {
    mode: 'concierge',
    page: { kind: 'agent-bundle', agent: weeklyDigest, revisionLabel: 'draft 019a' },
}
const conciergeRevisionsContext: ChatContext = {
    mode: 'concierge',
    page: { kind: 'agent-revisions', agent: weeklyDigest },
}
const conciergeSessionContext: ChatContext = {
    mode: 'concierge',
    page: { kind: 'agent-session', agent: weeklyDigest, sessionId: '01998a01' },
}
const playgroundContext: ChatContext = { mode: 'playground', agent: weeklyDigest }

/* ── Frames ────────────────────────────────────────────────────────
 * Same chat content, three presentation contexts. The lib should not
 * change at all between these — only the surrounding wrapper does.
 */

/** Default mode for the agent-console dock: fills the parent, no chrome. */
export const FrameEmbedded: Story = {
    args: { context: conciergeAgentContext, session: allSessionStates.idle },
}

/** Standalone card — useful for product surfaces that drop the chat into a flow. */
export const FrameRoundedCard: Story = {
    parameters: { layout: 'centered' },
    decorators: [
        (Story) => (
            <div className="h-[640px] w-[420px] overflow-hidden rounded-lg border border-border bg-background shadow-lg">
                <Story />
            </div>
        ),
    ],
    args: { context: conciergeAgentContext, session: allSessionStates.idle },
}

/* ── Inline-rendered client tools ──────────────────────────────────
 * Render-style client tools (`{ id, render }`) draw their UI inside the
 * matching `tool_call` card and resolve the call when the user submits.
 * The chat surface doesn't know what the UI is — it just hosts it and
 * forwards `onClientToolResolve` back to the runner. This story uses a
 * deliberately minimal inline form so the wiring is the point, not the
 * design. The agent console's `<SecretInline>` is the real example.
 */

const setSecretCallSession: ChatSession = {
    id: '01998a01-2222-7000-8000-0000000inline',
    application: weeklyDigest,
    principal: { kind: 'human', displayName: 'Ben', userId: 'u-1' },
    state: 'awaiting_client_tool',
    pendingApprovals: [],
    usage: { inputTokens: 1200, outputTokens: 400, costUsd: 0.01 },
    turns: [
        {
            kind: 'user',
            id: 'u-1',
            timestamp: '2026-05-31T17:30:00Z',
            text: 'Wire weekly-digest up to Anthropic so it can summarise the changelog.',
        },
        {
            kind: 'assistant',
            id: 'a-1',
            timestamp: '2026-05-31T17:30:04Z',
            parts: [
                {
                    kind: 'text',
                    text: "I'll need your Anthropic API key — set it inline below and I'll keep going.",
                },
                {
                    kind: 'tool_call',
                    toolId: 'set_secret',
                    callId: 'call-secret-1',
                    fulfillment: 'client',
                    args: { agent_slug: weeklyDigest.slug, secret: 'ANTHROPIC_KEY', mode: 'set' },
                    // No result yet — the chat renders the inline form
                    // and waits for the user to submit.
                },
            ],
        },
    ],
}

interface MockSetSecretArgs {
    secret: string
    mode?: 'set' | 'rotate'
}

function MockSetSecretForm({
    args,
    callbacks,
}: {
    args: MockSetSecretArgs
    callbacks: ClientToolRenderCallbacks
}): React.ReactElement {
    const [value, setValue] = useState('')
    const [done, setDone] = useState<null | 'saved' | 'cancelled'>(null)
    if (done === 'saved') {
        return (
            <div className="text-[0.6875rem] text-success-foreground">
                Secret <code className="font-mono">{args.secret}</code> saved.
            </div>
        )
    }
    if (done === 'cancelled') {
        return <div className="text-[0.6875rem] text-muted-foreground">Cancelled.</div>
    }
    return (
        <form
            className="space-y-1.5"
            onSubmit={(e) => {
                e.preventDefault()
                setDone('saved')
                callbacks.resolve({ key: args.secret, action: 'set' })
            }}
        >
            <div className="text-[0.6875rem] font-medium">
                {args.mode === 'rotate' ? 'Rotate' : 'Set'} <code className="font-mono">{args.secret}</code>
            </div>
            <div className="flex gap-1.5">
                <input
                    type="password"
                    value={value}
                    onChange={(e) => setValue(e.currentTarget.value)}
                    placeholder="paste value"
                    className="h-6 flex-1 rounded border border-border bg-background px-1.5 text-[0.6875rem]"
                />
                <button
                    type="submit"
                    disabled={!value}
                    className="rounded border border-border bg-primary px-1.5 text-[0.6875rem] font-medium text-primary-foreground disabled:opacity-50"
                >
                    Save
                </button>
                <button
                    type="button"
                    onClick={() => {
                        setDone('cancelled')
                        callbacks.reject('user_cancelled')
                    }}
                    className="rounded border border-border bg-card px-1.5 text-[0.6875rem]"
                >
                    Cancel
                </button>
            </div>
        </form>
    )
}

const mockSetSecretHandler: ClientToolHandler = {
    id: 'set_secret',
    render: (args, callbacks) => (
        <MockSetSecretForm args={args as unknown as MockSetSecretArgs} callbacks={callbacks} />
    ),
}

/**
 * Renders the chat at the moment the agent has invoked `set_secret`
 * and is waiting for the user. The card shows the inline form; once
 * the user submits, the renderer resolves the call (logged to the
 * action panel in storybook so you can see the payload).
 */
export const InlineClientToolCall: Story = {
    args: {
        context: { mode: 'concierge', page: { kind: 'agent', agent: weeklyDigest } },
        session: setSecretCallSession,
        handlers: [mockSetSecretHandler],
        onClientToolResolve: (callId, outcome) =>
            // eslint-disable-next-line no-console
            console.info('[story] onClientToolResolve', callId, outcome),
    },
}

/**
 * Same setup, but the session is already resolved (the tool call has
 * a result). Demonstrates that the inline UI gets torn down once the
 * agent receives a result — leaving the form around after the call is
 * done would be visually confusing.
 */
export const InlineClientToolCallResolved: Story = {
    args: {
        ...InlineClientToolCall.args,
        session: {
            ...setSecretCallSession,
            state: 'streaming',
            turns: ((): Turn[] => {
                const turns: Turn[] = [...setSecretCallSession.turns]
                const last = turns[turns.length - 1]
                if (last.kind !== 'assistant') {
                    return turns
                }
                turns[turns.length - 1] = {
                    ...last,
                    parts: last.parts.map((p) =>
                        p.kind === 'tool_call' && p.callId === 'call-secret-1'
                            ? { ...p, result: { ok: true, body: { key: 'ANTHROPIC_KEY', action: 'set' } } }
                            : p
                    ),
                }
                return turns
            })(),
        },
    },
}

/** Fullscreen mode — what a dedicated `/chat` page would look like. */
export const FrameFullscreen: Story = {
    parameters: { layout: 'fullscreen' },
    decorators: [
        (Story) => (
            <div className="flex h-screen w-screen items-stretch justify-center bg-muted/20">
                <div className="flex h-full w-full max-w-2xl flex-col bg-background">
                    <Story />
                </div>
            </div>
        ),
    ],
    args: { context: playgroundContext, session: allSessionStates.playground },
}

/* ── Waiting states ────────────────────────────────────────────────── */

export const WaitingOnAgentList: Story = {
    args: { context: conciergeListContext, session: allSessionStates.waiting },
}

export const WaitingOnAgent: Story = {
    args: { context: conciergeAgentContext, session: allSessionStates.waiting },
}

export const WaitingOnBundle: Story = {
    args: { context: conciergeBundleContext, session: allSessionStates.waiting },
}

export const WaitingOnRevisions: Story = {
    args: { context: conciergeRevisionsContext, session: allSessionStates.waiting },
}

export const WaitingOnSession: Story = {
    args: { context: conciergeSessionContext, session: allSessionStates.waiting },
}

export const WaitingInPlayground: Story = {
    args: { context: playgroundContext, session: allSessionStates.waiting },
}

/* ── Active conversation states (concierge) ────────────────────────── */

export const ConciergeMidConversation: Story = {
    args: { context: conciergeAgentContext, session: allSessionStates.idle },
}

export const ConciergeStreaming: Story = {
    args: { context: conciergeAgentContext, session: allSessionStates.streaming },
}

export const ConciergeAwaitingClientTool: Story = {
    args: { context: conciergeAgentContext, session: allSessionStates.awaitingClientTool },
}

export const ConciergeAwaitingApproval: Story = {
    args: { context: conciergeAgentContext, session: allSessionStates.awaitingApproval },
}

export const ConciergeDisconnected: Story = {
    args: { context: conciergeAgentContext, session: allSessionStates.disconnected },
}

export const ConciergeErrored: Story = {
    args: { context: conciergeAgentContext, session: allSessionStates.errored },
}

/* ── Playground mode ───────────────────────────────────────────────── */

export const PlaygroundActive: Story = {
    args: { context: playgroundContext, session: allSessionStates.playground },
}

/* ── Host-injected header ──────────────────────────────────────────── */

/**
 * Demonstrates `headerSlot` composition with a minimal placeholder.
 * The real console wraps a much richer `<DockHeader />` here —
 * mode pill, focus toggle, settings, exit-playground, etc.
 */
export const WithHostHeader: Story = {
    args: {
        context: conciergeAgentContext,
        session: allSessionStates.idle,
        headerSlot: (
            <div className="flex items-center gap-2 border-b border-border px-4 py-2.5 text-xs">
                <span className="inline-flex h-1.5 w-1.5 rounded-full bg-success-foreground" aria-hidden />
                <span className="font-medium uppercase tracking-wide text-muted-foreground">Demo header</span>
                <span className="ml-auto text-muted-foreground">host owns this row</span>
            </div>
        ),
    },
}
