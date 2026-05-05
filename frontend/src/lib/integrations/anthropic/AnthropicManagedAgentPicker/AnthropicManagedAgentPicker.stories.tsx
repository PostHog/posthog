import { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'
import { mockIntegration } from '~/test/mocks'

import { AnthropicManagedAgentPicker } from './AnthropicManagedAgentPicker'

const integration = { ...mockIntegration, id: 7, kind: 'anthropic' as const }

const sampleAgents = [
    { id: 'agt_support', name: 'Support bot', version: 'v3' },
    { id: 'agt_sales', name: 'Sales bot', version: 'v1' },
    { id: 'agt_analytics', name: 'Analytics assistant', version: null },
]

const meta: Meta<typeof AnthropicManagedAgentPicker> = {
    title: 'Components/Integrations/Anthropic Pickers/Agent',
    component: AnthropicManagedAgentPicker,
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

type Story = StoryObj<typeof AnthropicManagedAgentPicker>

export const Loaded: Story = {
    render: (args) => {
        useStorybookMocks({
            get: {
                '/api/projects/:id/integrations/:integration_id/anthropic_managed_agents/': {
                    agents: sampleAgents,
                    next_cursor: null,
                    has_more: false,
                },
            },
        })
        return <AnthropicManagedAgentPicker {...args} />
    },
}

export const HasMoreTruncation: Story = {
    name: 'has_more truncation hint',
    render: (args) => {
        useStorybookMocks({
            get: {
                '/api/projects/:id/integrations/:integration_id/anthropic_managed_agents/': {
                    agents: sampleAgents,
                    next_cursor: 'cursor_xyz',
                    has_more: true,
                },
            },
        })
        return <AnthropicManagedAgentPicker {...args} />
    },
}

export const Empty: Story = {
    render: (args) => {
        useStorybookMocks({
            get: {
                '/api/projects/:id/integrations/:integration_id/anthropic_managed_agents/': {
                    agents: [],
                    next_cursor: null,
                    has_more: false,
                },
            },
        })
        return <AnthropicManagedAgentPicker {...args} />
    },
}

export const MalformedResponse: Story = {
    name: 'malformed response (no agents key)',
    render: (args) => {
        useStorybookMocks({
            get: {
                '/api/projects/:id/integrations/:integration_id/anthropic_managed_agents/': {},
            },
        })
        return <AnthropicManagedAgentPicker {...args} />
    },
}

export const Loading: Story = {
    name: 'loading (request never resolves)',
    render: (args) => {
        useStorybookMocks({
            get: {
                '/api/projects/:id/integrations/:integration_id/anthropic_managed_agents/': () => new Promise(() => {}),
            },
        })
        return <AnthropicManagedAgentPicker {...args} />
    },
}
