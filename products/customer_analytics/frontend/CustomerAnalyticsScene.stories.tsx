import { Meta, StoryFn } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { useAvailableFeatures } from '~/mocks/features'
import { AvailableFeature } from '~/types'

import { BusinessType, customerAnalyticsSceneLogic } from './customerAnalyticsSceneLogic'

function setBusinessTypeOnMountedLogic(businessType: BusinessType): void {
    for (const logic of customerAnalyticsSceneLogic.findAllMounted()) {
        logic.actions.setBusinessType(businessType)
    }
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Customer Analytics/Dashboard',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2024-01-15',
        featureFlags: [FEATURE_FLAGS.CUSTOMER_ANALYTICS],
        testOptions: {
            waitForSelector: '[data-attr="customer-analytics-config"]',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                'api/environments/:team_id/customer_profile_configs/': { count: 0, results: [] },
            },
        }),
    ],
}
export default meta

export const B2CMode: StoryFn = () => {
    useDelayedOnMountEffect(() => {
        setBusinessTypeOnMountedLogic('b2c')
    })

    return <App />
}
B2CMode.parameters = {
    pageUrl: urls.customerAnalyticsDashboard(),
}

export const B2BModeWithGroupsEnabled: StoryFn = () => {
    useAvailableFeatures([AvailableFeature.GROUP_ANALYTICS])
    useStorybookMocks({
        get: {
            'api/environments/:team_id/groups_types/': [
                { group_type: 'organization', group_type_index: 0, name_singular: null, name_plural: null },
            ],
            'api/projects/:team_id/groups_types/': [
                { group_type: 'organization', group_type_index: 0, name_singular: null, name_plural: null },
            ],
        },
    })

    useDelayedOnMountEffect(() => {
        setBusinessTypeOnMountedLogic('b2b')
        for (const logic of customerAnalyticsSceneLogic.findAllMounted()) {
            logic.actions.setSelectedGroupType(0)
        }
    })

    return <App />
}
B2BModeWithGroupsEnabled.parameters = {
    pageUrl: urls.customerAnalyticsDashboard(),
}

export const B2BModeWithoutGroups: StoryFn = () => {
    useAvailableFeatures([])

    useDelayedOnMountEffect(() => {
        setBusinessTypeOnMountedLogic('b2b')
    })

    return <App />
}
B2BModeWithoutGroups.parameters = {
    pageUrl: urls.customerAnalyticsDashboard(),
}
