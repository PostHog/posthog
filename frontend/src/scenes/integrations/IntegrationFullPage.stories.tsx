import { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'
import { mockIntegration } from '~/test/mocks'

import { Slack } from './definitions'
import { IntegrationFullPage } from './IntegrationFullPage'

type StoryArgs = { connected?: boolean }

const meta: Meta<StoryArgs> = {
    title: 'Scenes-Other/Integration landing page',
    parameters: { layout: 'fullscreen', viewMode: 'story' },
    render: ({ connected = false }) => {
        useStorybookMocks({
            get: {
                '/api/projects/:id/integrations': { results: connected ? [mockIntegration] : [] },
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
