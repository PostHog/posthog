import { Meta, StoryObj } from '@storybook/react'

import { MCPHintToast } from './MCPHintToast'

const meta: Meta<typeof MCPHintToast> = {
    title: 'Components/MCP Hint Toast',
    component: MCPHintToast,
    parameters: {
        // The component is normally rendered inside a react-toastify toast.
        // The decorator below approximates that container so the story is visually meaningful.
        layout: 'centered',
    },
    decorators: [
        (Story) => (
            <div className="max-w-md min-w-140 bg-surface-primary border border-primary rounded-lg shadow-lg p-3">
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof MCPHintToast>

export const FeatureFlagsCreate: Story = {
    args: { surfaceKey: 'feature_flags.create' },
}

export const FeatureFlagsUpdateWithDerivedPrompt: Story = {
    args: { surfaceKey: 'feature_flags.update', derivedPrompt: '"Bump rollout for new-checkout to 50%"' },
}

export const DashboardsCreate: Story = {
    args: { surfaceKey: 'dashboards.create' },
}

export const ExperimentsCreate: Story = {
    args: { surfaceKey: 'experiments.create' },
}

export const SqlExecute: Story = {
    args: { surfaceKey: 'sql.execute' },
}

export const AnnotationsCreate: Story = {
    args: { surfaceKey: 'annotations.create' },
}
