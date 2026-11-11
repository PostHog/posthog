import type { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'

import { LLMProviderKeysSettings } from './LLMProviderKeysSettings'
import { SystemOneConnectionFields } from './SystemOneConnectionFields'

const meta: Meta<typeof SystemOneConnectionFields> = {
    title: 'Scenes-App/AI observability/System One connection',
    component: SystemOneConnectionFields,
    decorators: [
        (Story) => {
            useStorybookMocks({
                get: {
                    '/api/environments/:team_id/llm_analytics/provider_keys/': { results: [] },
                    '/api/environments/:team_id/llm_analytics/evaluation_config/': { active_provider_key: null },
                },
            })
            return <Story />
        },
    ],
}

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {}
export const ProviderSettings: Story = { render: () => <LLMProviderKeysSettings /> }
