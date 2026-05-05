import { Meta, StoryObj } from '@storybook/react'

import { mockBasicUser } from '~/test/mocks'
import { IntegrationType } from '~/types'

import { IntegrationView } from './IntegrationView'

const baseAnthropic: IntegrationType = {
    id: 7,
    kind: 'anthropic',
    config: { workspace_label: 'Production' },
    icon_url: '/static/services/anthropic.svg',
    display_name: 'Production',
    created_at: '2026-05-01T12:00:00Z',
    created_by: mockBasicUser,
}

const baseSlack: IntegrationType = {
    id: 8,
    kind: 'slack',
    config: { team: { id: '123', name: 'PostHog' } },
    icon_url: '/static/services/slack.png',
    display_name: '#general',
    created_at: '2026-05-01T12:00:00Z',
    created_by: mockBasicUser,
}

const meta: Meta<typeof IntegrationView> = {
    title: 'Components/Integrations/IntegrationView',
    component: IntegrationView,
    decorators: [
        (Story) => (
            <div className="p-4 max-w-3xl">
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof IntegrationView>

export const Anthropic_Healthy: Story = {
    name: 'Anthropic — healthy',
    args: { integration: baseAnthropic },
}

export const Anthropic_AuthFailed: Story = {
    name: 'Anthropic — auth failed (no Reconnect button)',
    args: {
        integration: { ...baseAnthropic, errors: 'TOKEN_REFRESH_FAILED' },
    },
}

export const Slack_AuthFailed: Story = {
    name: 'Slack (OAuth) — auth failed (Reconnect button visible)',
    args: {
        integration: { ...baseSlack, errors: 'TOKEN_REFRESH_FAILED' },
    },
}
