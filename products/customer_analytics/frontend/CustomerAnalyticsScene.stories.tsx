import { Meta, StoryObj } from '@storybook/react'
import posthog from 'posthog-js'

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

type Story = StoryObj<{}>

export const B2CMode: Story = {
    render: () => {
        useDelayedOnMountEffect(() => {
            setBusinessTypeOnMountedLogic('b2c')
        })

        return <App />
    },
    parameters: {
        pageUrl: urls.customerAnalyticsDashboard(),
    },
}

export const B2BModeWithGroupsEnabled: Story = {
    render: () => {
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
    },
    parameters: {
        pageUrl: urls.customerAnalyticsDashboard(),
    },
}

export const B2BModeWithoutGroups: Story = {
    render: () => {
        useAvailableFeatures([])

        useDelayedOnMountEffect(() => {
            setBusinessTypeOnMountedLogic('b2b')
        })

        return <App />
    },
    parameters: {
        pageUrl: urls.customerAnalyticsDashboard(),
    },
}

export const GatedWithoutMatchingEarlyAccessFeature: Story = {
    render: () => <App />,
    parameters: {
        featureFlags: [],
        pageUrl: urls.customerAnalyticsDashboard(),
        testOptions: {
            waitForSelector: '[data-attr="product-introduction-feature"]',
        },
    },
}

export const GatedWithFeatureToggle: Story = {
    render: () => {
        // Mock synchronously during render so the gate's mount useEffect —
        // which calls `posthog.getEarlyAccessFeatures(callback)` — uses our data.
        ;(posthog as any).getEarlyAccessFeatures = (callback: (features: any[]) => void): void =>
            callback([
                {
                    flagKey: FEATURE_FLAGS.CUSTOMER_ANALYTICS,
                    name: 'Customer analytics',
                    description: 'Understand how your customers interact with your product',
                    stage: 'beta',
                    documentationUrl: '',
                    payload: {},
                },
            ])
        return <App />
    },
    parameters: {
        featureFlags: [],
        pageUrl: urls.customerAnalyticsDashboard(),
        testOptions: {
            waitForSelector: '#feature-preview-gate-switch',
        },
    },
}
