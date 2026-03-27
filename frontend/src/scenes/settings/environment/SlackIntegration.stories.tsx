import { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'
import { useAvailableFeatures } from '~/mocks/features'
import { mockIntegration } from '~/test/mocks'
import { AvailableFeature } from '~/types'

import { SlackIntegration } from './SlackIntegration'

type StoryArgs = { instanceConfigured?: boolean; integrated?: boolean }

const meta: Meta<StoryArgs> = {
    title: 'Components/Integrations/Slack',
    component: SlackIntegration,
    parameters: {},
    render: ({ instanceConfigured = true, integrated = false }) => {
        useAvailableFeatures([AvailableFeature.SUBSCRIPTIONS])

        useStorybookMocks({
            get: {
                '/api/projects/:id/integrations': { results: integrated ? [mockIntegration] : [] },
                '/api/instance_settings': {
                    results: instanceConfigured
                        ? [
                              {
                                  key: 'SLACK_APP_CLIENT_ID',
                                  value: '910200304849.3676478528614',
                              },
                              {
                                  key: 'SLACK_APP_CLIENT_SECRET',
                                  value: '*****',
                              },
                          ]
                        : [],
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
