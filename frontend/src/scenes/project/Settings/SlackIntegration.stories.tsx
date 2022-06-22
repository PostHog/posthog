import React from 'react'
import { ComponentMeta } from '@storybook/react'
import { AvailableFeature } from '~/types'
import { useAvailableFeatures } from '~/mocks/features'
import { useFeatureFlags, useStorybookMocks } from '~/mocks/browser'
import { FEATURE_FLAGS } from 'lib/constants'
import { mockIntegration } from '~/test/mocks'
import { SlackIntegration } from './SlackIntegration'

export default {
    title: 'Components/Integrations/Slack',
    component: SlackIntegration,
} as ComponentMeta<typeof SlackIntegration>

const Template = (args: { instanceConfigured?: boolean; integrated?: boolean }): JSX.Element => {
    const { instanceConfigured = true, integrated = false } = args

    useAvailableFeatures([AvailableFeature.SUBSCRIPTIONS])
    useFeatureFlags([FEATURE_FLAGS.SUBSCRIPTIONS_SLACK])

    useStorybookMocks({
        get: {
            '/api/projects/:id/integrations': { results: integrated ? [mockIntegration] : [] },
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
