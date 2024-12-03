import { Meta } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'
import { useAvailableFeatures } from '~/mocks/features'
import { mockIntegration } from '~/test/mocks'
import { AvailableFeature } from '~/types'

import { SlackIntegration } from './SlackIntegration'

const meta: Meta<typeof SlackIntegration> = {
    title: 'Components/Integrations/Slack',
    component: SlackIntegration,
    parameters: {},
}
export default meta

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
