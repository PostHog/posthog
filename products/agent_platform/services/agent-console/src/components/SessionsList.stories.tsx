import type { Meta, StoryObj } from '@storybook/react'

import { listSessionsForAgentFixture, weeklyDigest } from '@posthog/agent-chat/fixtures'

import { SessionsList } from './SessionsList'

const meta: Meta<typeof SessionsList> = {
    title: 'Agent console components/SessionsList',
    component: SessionsList,
    parameters: { layout: 'centered' },
    decorators: [
        (Story) => (
            <div className="h-[640px] w-[860px]">
                <Story />
            </div>
        ),
    ],
}

export default meta
type Story = StoryObj<typeof SessionsList>

const onOpenSession = (id: string): void => console.info('[mock] openSession', id)
const weeklyDigestSessions = listSessionsForAgentFixture(weeklyDigest.id)

export const Default: Story = {
    args: { sessions: weeklyDigestSessions, onOpenSession },
}

export const Empty: Story = {
    args: { sessions: [], onOpenSession },
}

export const Selected: Story = {
    args: {
        sessions: weeklyDigestSessions,
        selectedSessionId: weeklyDigestSessions[1]?.id ?? null,
        onOpenSession,
    },
}

export const NarrowColumn: Story = {
    decorators: [(Story) => <div className="h-[640px] w-[340px]">{Story()}</div>],
    args: {
        sessions: weeklyDigestSessions,
        selectedSessionId: weeklyDigestSessions[0]?.id ?? null,
        onOpenSession,
    },
}

export const WithLoadMore: Story = {
    args: {
        sessions: weeklyDigestSessions,
        totalCount: weeklyDigestSessions.length + 25,
        hasMore: true,
        onOpenSession,
        onLoadMore: () => console.info('[mock] loadMore'),
    },
}

export const OnlyCompleted: Story = {
    args: {
        sessions: weeklyDigestSessions.filter((s) => s.state === 'completed'),
        onOpenSession,
    },
}

export const OnlyLive: Story = {
    args: {
        sessions: weeklyDigestSessions.filter((s) =>
            ['idle', 'streaming', 'awaiting_user_input', 'awaiting_client_tool', 'disconnected'].includes(s.state)
        ),
        onOpenSession,
    },
}
