import type { Meta, StoryObj } from '@storybook/react'

import { agents, fleetApprovals, releaseConcierge } from '@posthog/agent-chat/fixtures'

import { type AgentLookup, ApprovalsList } from './ApprovalsList'

const agentsById: AgentLookup = new Map(agents.map((a) => [a.id, { id: a.id, name: a.name, slug: a.slug }]))

const meta: Meta<typeof ApprovalsList> = {
    title: 'Agent console components/ApprovalsList',
    component: ApprovalsList,
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
type Story = StoryObj<typeof ApprovalsList>

const onOpenApproval = (id: string): void => console.info('[mock] openApproval', id)

export const Fleet: Story = {
    args: { approvals: fleetApprovals, agentsById, showAgentColumn: true, onOpenApproval },
}

export const FleetWithSelection: Story = {
    args: {
        approvals: fleetApprovals,
        agentsById,
        showAgentColumn: true,
        selectedApprovalId: fleetApprovals.find((a) => a.state === 'queued')?.id ?? null,
        onOpenApproval,
    },
}

export const PerAgent: Story = {
    args: {
        approvals: fleetApprovals.filter((a) => a.application_id === releaseConcierge.id),
        agentsById: new Map([[releaseConcierge.id, releaseConcierge]]),
        showAgentColumn: false,
        onOpenApproval,
    },
}

export const Empty: Story = {
    args: { approvals: [], agentsById, showAgentColumn: true, onOpenApproval },
}
