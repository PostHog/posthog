import { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { mockIntegration } from '~/test/mocks'
import { Realm } from '~/types'

import { Slack } from './definitions'
import { IntegrationFullPage } from './IntegrationFullPage'

type StoryArgs = { connected?: boolean }

const meta: Meta<StoryArgs> = {
    title: 'Scenes-Other/Integration landing page',
    parameters: { layout: 'fullscreen', viewMode: 'story' },
    render: ({ connected = false }) => {
        useStorybookMocks({
            get: {
                // integrationsLogic loads from the environments endpoint, not projects
                '/api/environments/:id/integrations': { results: connected ? [mockIntegration] : [] },
                // slack_service.available drives whether the "Add to Slack" connect button shows
                '/_preflight': {
                    ...preflightJson,
                    realm: Realm.Cloud,
                    slack_service: { available: true, client_id: 'test-client-id' },
                },
            },
        })

        return <IntegrationFullPage definition={Slack} SettingsSection={Slack.SettingsSection} />
    },
}
export default meta

type Story = StoryObj<StoryArgs>

export const NotConnected: Story = {}

export const Connected: Story = {
    args: { connected: true },
}
