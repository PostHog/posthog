import type { Meta, StoryObj } from '@storybook/react'

import { EditWithAIButton } from './EditWithAIButton'

const meta: Meta<typeof EditWithAIButton> = {
    title: 'Agent console components/EditWithAIButton',
    component: EditWithAIButton,
    parameters: { layout: 'centered' },
}

export default meta
type Story = StoryObj<typeof EditWithAIButton>

/**
 * Default pill — what shows up next to an agent header or a spec
 * section row. Clicking outside Storybook fires the dock seed, but
 * the dock isn't mounted here so the button is no-op.
 */
export const Default: Story = {
    args: {
        prompt: 'Help me edit the `weekly-digest` agent.',
        agentSlug: 'weekly-digest',
    },
}

export const Compact: Story = {
    args: {
        prompt: 'Help me change the `model` for `weekly-digest`.',
        agentSlug: 'weekly-digest',
        label: 'Edit',
        compact: true,
    },
}

/**
 * Long label variant. Used on the agents-list page header where the
 * button needs to read as a discoverable "create with AI" CTA rather
 * than a small section pill.
 */
export const LongLabel: Story = {
    args: {
        prompt: 'Help me create a new agent.',
        label: 'New agent with AI',
    },
}

/**
 * Several pills on one row — the per-section pattern in the agent config
 * surface. Confirms the button keeps a tight footprint when stacked next
 * to its peers.
 */
export const StackedRow: Story = {
    render: () => (
        <div className="flex items-center gap-2">
            <EditWithAIButton prompt="Help me change the model for weekly-digest." label="Edit" compact />
            <EditWithAIButton prompt="Help me change the triggers for weekly-digest." label="Edit" compact />
            <EditWithAIButton prompt="Help me change the tools for weekly-digest." label="Edit" compact />
        </div>
    ),
}
