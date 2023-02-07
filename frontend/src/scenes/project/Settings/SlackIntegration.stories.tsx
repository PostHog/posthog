import { ComponentMeta } from '@storybook/react'
import { AvailableFeature } from '~/types'
import { useAvailableFeatures } from '~/mocks/features'
import { useStorybookMocks } from '~/mocks/browser'
import { mockIntegration } from '~/test/mocks'
import { SlackIntegration } from './SlackIntegration'

export default {
    title: 'Components/Integrations/Slack',
    component: SlackIntegration,
    parameters: {},
} as ComponentMeta<typeof SlackIntegration>

const Template = (args: { instanceConfigured?: boolean; integrated?: boolean }): JSX.Element => {
    const { instanceConfigured = true, integrated = false } = args

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
}

export const SlackIntegration_ = (): JSX.Element => {
    return <Template />
}

export const SlackIntegrationInstanceNotConfigured = (): JSX.Element => {
    return <Template instanceConfigured={false} />
}

export const SlackIntegrationAdded = (): JSX.Element => {
    return <Template integrated />
}
