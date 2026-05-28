/**
 * Stories for `<AgentChat />`. Two axes:
 *  - **Context**: concierge (per page kind) + playground (per agent)
 *  - **Session state**: waiting → idle → streaming → ... → error
 *
 * Each named story exercises one combination so visual snapshots in CI
 * give us coverage by combination, not by axis.
 */

import type { Meta, StoryObj } from '@storybook/react'
import { AgentChat } from './AgentChat'
import type { ChatContext } from './context'
import {
    allSessionStates,
    weeklyDigest,
} from './fixtures'

const meta: Meta<typeof AgentChat> = {
    title: 'Agent Chat/AgentChat',
    component: AgentChat,
    parameters: {
        layout: 'centered',
    },
    decorators: [
        (Story) => (
            <div className="h-[640px] w-[360px] border-l border-border">
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
