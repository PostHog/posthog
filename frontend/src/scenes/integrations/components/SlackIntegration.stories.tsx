import { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'
import { useAvailableFeatures } from '~/mocks/features'
import { mockIntegration } from '~/test/mocks'
import {
    AvailableFeature,
    IntegrationType,
    SLACK_INTEGRATION_SCOPES,
    SLACK_INTEGRATION_SCOPES_IN_REVIEW,
} from '~/types'

import { Slack } from '../definitions/slack'
import { SlackIntegration } from './SlackIntegration'

type StoryArgs = { instanceConfigured?: boolean; integrated?: boolean }

const SLACK_INSTANCE_SETTINGS = [
    { key: 'SLACK_APP_CLIENT_ID', value: '910200304849.3676478528614' },
    { key: 'SLACK_APP_CLIENT_SECRET', value: '*****' },
]

const meta: Meta<StoryArgs> = {
    title: 'Components/Integrations/Slack',
    parameters: { mockDate: '2023-01-01' },
    render: ({ instanceConfigured = true, integrated = false }) => {
        useAvailableFeatures([AvailableFeature.SUBSCRIPTIONS])

        useStorybookMocks({
            get: {
                '/api/environments/:id/integrations': { results: integrated ? [mockIntegration] : [] },
                '/api/instance_settings': {
                    results: instanceConfigured ? SLACK_INSTANCE_SETTINGS : [],
                },
            },
        })

        return <SlackIntegration />
    },
}
export default meta

type Story = StoryObj<StoryArgs>

export const SlackIntegration_: Story = {}

export const SlackIntegrationInstanceNotConfigured: Story = {
    args: { instanceConfigured: false },
}

export const SlackIntegrationAdded: Story = {
    args: { integrated: true },
}

// ---- OAuth landing page (``/project/:id/integrations/slack``) ----------------------------
//
// The settings-side ``SlackIntegration`` component above does not exercise the full-page
// success / warning surface that the OAuth callback lands users on. These stories render
// ``Slack.FullPage`` against a mocked integrations endpoint so the green-success and
// missing-scope warning states appear in snapshot diffs.

const renderFullPage = ({ integrations }: { integrations: IntegrationType[] }): JSX.Element => {
    useAvailableFeatures([AvailableFeature.SUBSCRIPTIONS])
    useStorybookMocks({
        get: {
            '/api/environments/:id/integrations': { results: integrations },
            '/api/instance_settings': { results: SLACK_INSTANCE_SETTINGS },
        },
    })
    return <Slack.FullPage />
}

const mockSlackIntegrationWithScopes = (scopes: string[]): IntegrationType => ({
    ...mockIntegration,
    config: { ...mockIntegration.config, scope: scopes.join(',') },
})

export const SlackFullPageConnect: StoryObj = {
    name: 'Full Page — Connect',
    render: () => renderFullPage({ integrations: [] }),
}

export const SlackFullPageConnectedAllScopes: StoryObj = {
    name: 'Full Page — Connected (all scopes)',
    // Storybook runs with ``isDev === true``, so ``useSlackRequiredScopes`` returns the union
    // of the always-on and in-review sets. Mirror that here so the green-success state isn't
    // immediately undone by missing in-review scopes.
    render: () =>
        renderFullPage({
            integrations: [
                mockSlackIntegrationWithScopes([...SLACK_INTEGRATION_SCOPES, ...SLACK_INTEGRATION_SCOPES_IN_REVIEW]),
            ],
        }),
}

export const SlackFullPageConnectedMissingScopes: StoryObj = {
    name: 'Full Page — Connected (missing scopes)',
    render: () =>
        renderFullPage({
            // A legacy notifications-only scope set: enough to send messages, but missing
            // app_mentions:read / users:read* etc., so the page should flip into "needs attention".
            integrations: [
                mockSlackIntegrationWithScopes(['channels:read', 'groups:read', 'chat:write', 'chat:write.customize']),
            ],
        }),
}
