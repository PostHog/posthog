import { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'
import { mockIntegration } from '~/test/mocks'

import { AnthropicManagedAgentEnvironmentPicker } from './AnthropicManagedAgentEnvironmentPicker'

const integration = { ...mockIntegration, id: 7, kind: 'anthropic' as const }

const sampleEnvironments = [
    { id: 'env_prod', name: 'Production' },
    { id: 'env_staging', name: 'Staging' },
    { id: 'env_dev', name: 'Development' },
]

const meta: Meta<typeof AnthropicManagedAgentEnvironmentPicker> = {
    title: 'Components/Integrations/Anthropic Pickers/Environment',
    component: AnthropicManagedAgentEnvironmentPicker,
    args: { integration },
    decorators: [
        (Story) => (
            <div className="p-4 max-w-md">
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof AnthropicManagedAgentEnvironmentPicker>

export const Loaded: Story = {
    render: (args) => {
        useStorybookMocks({
            get: {
                '/api/projects/:id/integrations/:integration_id/anthropic_managed_agent_environments/': {
                    environments: sampleEnvironments,
                    next_cursor: null,
                    has_more: false,
                },
            },
        })
        return <AnthropicManagedAgentEnvironmentPicker {...args} />
    },
}

export const HasMoreTruncation: Story = {
    name: 'has_more truncation hint',
    render: (args) => {
        useStorybookMocks({
            get: {
                '/api/projects/:id/integrations/:integration_id/anthropic_managed_agent_environments/': {
                    environments: sampleEnvironments,
                    next_cursor: 'cursor_xyz',
                    has_more: true,
                },
            },
        })
        return <AnthropicManagedAgentEnvironmentPicker {...args} />
    },
}

export const Empty: Story = {
    render: (args) => {
        useStorybookMocks({
            get: {
                '/api/projects/:id/integrations/:integration_id/anthropic_managed_agent_environments/': {
                    environments: [],
                    next_cursor: null,
                    has_more: false,
                },
            },
        })
        return <AnthropicManagedAgentEnvironmentPicker {...args} />
    },
}
