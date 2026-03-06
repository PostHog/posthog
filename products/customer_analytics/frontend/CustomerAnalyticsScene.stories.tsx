import { Meta, StoryFn } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { useAvailableFeatures } from '~/mocks/features'
import { AvailableFeature } from '~/types'

import { customerAnalyticsSceneLogic } from './customerAnalyticsSceneLogic'

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Customer Analytics/Dashboard',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2024-01-15',
        testOptions: {
            waitForSelector: '.PayGateMini,.InsightCard',
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
    const { setBusinessType } = useActions(customerAnalyticsSceneLogic)

    useEffect(() => {
        setBusinessType('b2c')
    }, [setBusinessType])

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

    const { setBusinessType, setSelectedGroupType } = useActions(customerAnalyticsSceneLogic)

    useEffect(() => {
        setBusinessType('b2b')
        setSelectedGroupType(0)
    }, [setBusinessType, setSelectedGroupType])

    return <App />
}
B2BModeWithGroupsEnabled.parameters = {
    pageUrl: urls.customerAnalyticsDashboard(),
}

export const B2BModeWithoutGroups: StoryFn = () => {
    useAvailableFeatures([])

    const { setBusinessType } = useActions(customerAnalyticsSceneLogic)

    useEffect(() => {
        setBusinessType('b2b')
    }, [setBusinessType])

    return <App />
}
B2BModeWithoutGroups.parameters = {
    pageUrl: urls.customerAnalyticsDashboard(),
    testOptions: {
        waitForSelector: '.PayGateMini',
    },
}
