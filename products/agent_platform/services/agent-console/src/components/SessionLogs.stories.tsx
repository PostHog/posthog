import type { Meta, StoryObj } from '@storybook/react'

import { listLogsForSessionFixture } from '@posthog/agent-chat/fixtures'

import { SessionLogs } from './SessionLogs'

const meta: Meta<typeof SessionLogs> = {
    title: 'Agent console components/SessionLogs',
    component: SessionLogs,
    parameters: { layout: 'centered' },
    decorators: [
        (Story) => (
            <div className="h-[520px] w-[640px]">
                <Story />
            </div>
        ),
    ],
}

export default meta
type Story = StoryObj<typeof SessionLogs>

const chatLogs = listLogsForSessionFixture('01998a01-2222-7000-8000-0000000007d2')
const failedLogs = listLogsForSessionFixture('01998a01-2222-7000-8000-0000000007d3')
const slackLogs = listLogsForSessionFixture('01998a01-2222-7000-8000-0000000007e2')
const awaitingApprovalLogs = listLogsForSessionFixture('01998a01-2222-7000-8000-000000000102')

export const ChatSession: Story = {
    args: { logs: chatLogs, sessionStartedAt: chatLogs[0]?.ts },
}

export const FailedSession: Story = {
    args: { logs: failedLogs, sessionStartedAt: failedLogs[0]?.ts },
}

export const SlackSession: Story = {
    args: { logs: slackLogs, sessionStartedAt: slackLogs[0]?.ts },
}

export const AwaitingApproval: Story = {
    args: { logs: awaitingApprovalLogs, sessionStartedAt: awaitingApprovalLogs[0]?.ts },
}

export const Empty: Story = {
    args: { logs: [] },
}
