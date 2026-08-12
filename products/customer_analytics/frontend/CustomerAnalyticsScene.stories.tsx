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

export const FeatureRequests: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                'api/projects/:team_id/feature_requests/': {
                    count: 1,
                    next: null,
                    previous: null,
                    results: [
                        {
                            id: '018f47de-7e12-7000-8000-000000000001',
                            title: 'Export account-level retention data',
                            description: 'The customer needs this export for their monthly reporting workflow.',
                            request_status: 'requested',
                            account: { id: '018f47de-7e12-7000-8000-000000000002', name: 'Acme' },
                            product_areas: [
                                {
                                    id: '018f47de-7e12-7000-8000-000000000003',
                                    name: 'Product analytics',
                                    display_order: 1,
                                    is_active: true,
                                    created_at: '2024-01-10T10:00:00Z',
                                    updated_at: '2024-01-10T10:00:00Z',
                                },
                                {
                                    id: '018f47de-7e12-7000-8000-000000000004',
                                    name: 'Data warehouse',
                                    display_order: 2,
                                    is_active: true,
                                    created_at: '2024-01-10T10:00:00Z',
                                    updated_at: '2024-01-10T10:00:00Z',
                                },
                            ],
                            created_by: 1,
                            updated_by: 1,
                            created_at: '2024-01-12T10:00:00Z',
                            updated_at: '2024-01-14T10:00:00Z',
                        },
                    ],
                },
                'api/projects/:team_id/feature_request_product_areas/': [],
            },
        })
        return <App />
    },
    parameters: {
        featureFlags: [FEATURE_FLAGS.CUSTOMER_ANALYTICS, FEATURE_FLAGS.CUSTOMER_ANALYTICS_FEATURE_REQUESTS],
        pageUrl: urls.customerAnalyticsFeatureRequests(),
        testOptions: {
            waitForSelector: '[data-attr="new-feature-request"]',
        },
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
