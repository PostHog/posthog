/**
 * `<ApprovalDetail>` stories — the right pane of the approvals
 * master-detail layout.
 *
 * The panel fetches the approval, its session, and its logs through
 * `apiClient`, so each story wraps it in `<SessionProvider>` +
 * `<SessionGate>` (resolves `teamId` from the mocked `/api/auth/me`) and
 * relies on the MSW approval handlers in `.storybook/mocks/`. Switch to
 * the **Session** tab to see the conversation that proposed the call.
 */

import type { Meta, StoryObj } from '@storybook/react'

import type { AgentApplicationFixture } from '@posthog/agent-chat/fixtures'
import {
    dispatchedApproval,
    dispatchedFailedApproval,
    incidentTriager,
    queuedPrApproval,
    queuedTeamDeleteApproval,
    rejectedApproval,
    releaseConcierge,
    weeklyDigest,
} from '@posthog/agent-chat/fixtures'

import { SessionGate, SessionProvider } from '@/components/session-context'

import { ApprovalDetail } from './ApprovalDetail'

const toAgent = (a: AgentApplicationFixture): { id: string; name: string; slug: string } => ({
    id: a.id,
    name: a.name,
    slug: a.slug,
})

const noop = (): void => undefined

const meta: Meta<typeof ApprovalDetail> = {
    title: 'Agent console components/Pages/Approval Detail',
    component: ApprovalDetail,
    parameters: { layout: 'fullscreen' },
    decorators: [
        (Story) => (
            <SessionProvider>
                <SessionGate>
                    <div className="h-screen w-full max-w-3xl border-l border-border">
                        <Story />
                    </div>
                </SessionGate>
            </SessionProvider>
        ),
    ],
}

export default meta
type Story = StoryObj<typeof ApprovalDetail>

export const QueuedEditable: Story = {
    args: {
        approvalId: queuedPrApproval.id,
        agent: toAgent(releaseConcierge),
        onClose: noop,
        onDecided: noop,
    },
}

export const QueuedReadOnly: Story = {
    args: {
        approvalId: queuedTeamDeleteApproval.id,
        agent: toAgent(incidentTriager),
        onClose: noop,
        onDecided: noop,
    },
}

export const Dispatched: Story = {
    args: {
        approvalId: dispatchedApproval.id,
        agent: toAgent(releaseConcierge),
        onClose: noop,
        onDecided: noop,
    },
}

export const Rejected: Story = {
    args: {
        approvalId: rejectedApproval.id,
        agent: toAgent(weeklyDigest),
        onClose: noop,
        onDecided: noop,
    },
}

export const DispatchFailed: Story = {
    args: {
        approvalId: dispatchedFailedApproval.id,
        agent: toAgent(weeklyDigest),
        onClose: noop,
        onDecided: noop,
    },
}
