import { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'
import { mockIntegration } from '~/test/mocks'

import { AnthropicManagedAgentVaultPicker } from './AnthropicManagedAgentVaultPicker'

const integration = { ...mockIntegration, id: 7, kind: 'anthropic' as const }

const sampleVaults = [
    { id: 'vault_customer', display_name: 'Customer secrets' },
    { id: 'vault_billing', display_name: 'Billing keys' },
]

const meta: Meta<typeof AnthropicManagedAgentVaultPicker> = {
    title: 'Components/Integrations/Anthropic Pickers/Vault',
    component: AnthropicManagedAgentVaultPicker,
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

type Story = StoryObj<typeof AnthropicManagedAgentVaultPicker>

export const Loaded: Story = {
    render: (args) => {
        useStorybookMocks({
            get: {
                '/api/projects/:id/integrations/:integration_id/anthropic_managed_agent_vaults/': {
                    vaults: sampleVaults,
                    next_cursor: null,
                    has_more: false,
                },
            },
        })
        return <AnthropicManagedAgentVaultPicker {...args} />
    },
}

export const Empty: Story = {
    render: (args) => {
        useStorybookMocks({
            get: {
                '/api/projects/:id/integrations/:integration_id/anthropic_managed_agent_vaults/': {
                    vaults: [],
                    next_cursor: null,
                    has_more: false,
                },
            },
        })
        return <AnthropicManagedAgentVaultPicker {...args} />
    },
}
