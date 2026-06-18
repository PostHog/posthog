import { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { mockIntegration } from '~/test/mocks'
import { Realm } from '~/types'

import { Slack } from './definitions'
import { IntegrationFullPage } from './IntegrationFullPage'

const meta: Meta<typeof IntegrationFullPage> = {
    title: 'Scenes-Other/Integration landing page',
    component: IntegrationFullPage,
    parameters: { layout: 'fullscreen', viewMode: 'story' },
    decorators: [
        mswDecorator({
            get: {
                // slack_service.available drives whether the "Add to Slack" connect button shows
                '/_preflight': {
                    ...preflightJson,
                    realm: Realm.Cloud,
                    slack_service: { available: true, client_id: 'test-client-id' },
                },
            },
        }),
    ],
    render: () => <IntegrationFullPage definition={Slack} SettingsSection={Slack.SettingsSection} />,
}
export default meta

type Story = StoryObj<typeof IntegrationFullPage>

// integrationsLogic loads from the environments endpoint, not projects
export const NotConnected: Story = {
    decorators: [mswDecorator({ get: { '/api/environments/:id/integrations': { results: [] } } })],
}

export const Connected: Story = {
    decorators: [mswDecorator({ get: { '/api/environments/:id/integrations': { results: [mockIntegration] } } })],
}
