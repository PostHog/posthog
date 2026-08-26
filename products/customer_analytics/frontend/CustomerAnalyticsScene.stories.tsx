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

const featureRequestStoryItem = {
    id: '018f47de-7e12-7000-8000-000000000001',
    title: 'Export account-level retention data',
    description: 'The customer needs this export for their monthly reporting workflow.',
    request_status: 'planned',
    request_priority: 'high',
    is_archived: false,
    archived_at: null,
    archived_by: null,
    version: 1,
    account: { id: '018f47de-7e12-7000-8000-000000000002', name: 'Acme' },
    account_links: [
        {
            id: '018f47de-7e12-7000-8000-000000000007',
            account: { id: '018f47de-7e12-7000-8000-000000000002', name: 'Acme' },
            evidence: [
                {
                    id: '018f47de-7e12-7000-8000-000000000008',
                    summary: 'Acme needs a monthly export for its reporting workflow.',
                    customer_quote: 'We need to share account retention with our leadership team.',
                    evidence_source: 'conversation',
                    source_url: '',
                    requested_on: '2024-01-08',
                    image_ids: ['018f47de-7e12-7000-8000-000000000030'],
                    created_by: 1,
                    updated_by: 1,
                    created_at: '2024-01-12T10:00:00Z',
                    updated_at: '2024-01-12T10:00:00Z',
                },
                ...Array.from({ length: 5 }, (_, index) => ({
                    id: `018f47de-7e12-7000-8000-00000000001${index}`,
                    summary: `Acme repeated this request in follow-up ${index + 1}.`,
                    customer_quote: '',
                    evidence_source: 'meeting',
                    source_url: '',
                    requested_on: `2024-01-${String(index + 9).padStart(2, '0')}`,
                    image_ids: [],
                    created_by: 1,
                    updated_by: 1,
                    created_at: `2024-01-${String(index + 13).padStart(2, '0')}T10:00:00Z`,
                    updated_at: `2024-01-${String(index + 13).padStart(2, '0')}T10:00:00Z`,
                })),
            ],
            created_at: '2024-01-12T10:00:00Z',
            updated_at: '2024-01-12T10:00:00Z',
        },
        {
            id: '018f47de-7e12-7000-8000-000000000009',
            account: { id: '018f47de-7e12-7000-8000-000000000010', name: 'Globex' },
            evidence: [],
            created_at: '2024-01-13T10:00:00Z',
            updated_at: '2024-01-13T10:00:00Z',
        },
    ],
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
    created_by: 178,
    updated_by: 1,
    created_at: '2024-01-12T10:00:00Z',
    updated_at: '2024-01-14T10:00:00Z',
}

export const FeatureRequests: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/uploaded_media/:id': () =>
                    new Response(
                        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 360"><rect width="640" height="360" fill="#f0f0eb"/><rect x="80" y="70" width="480" height="220" rx="8" fill="#fff" stroke="#bbb"/><text x="320" y="185" text-anchor="middle" font-family="sans-serif" font-size="24" fill="#444">Retention export preview</text></svg>',
                        { headers: { 'Content-Type': 'image/svg+xml' } }
                    ),
                'api/projects/:team_id/feature_requests/': {
                    count: 1,
                    next: null,
                    previous: null,
                    results: [featureRequestStoryItem],
                },
                'api/projects/:team_id/feature_requests/:id/': featureRequestStoryItem,
                'api/projects/:team_id/feature_requests/:id/history/': [
                    {
                        id: '018f47de-7e12-7000-8000-000000000006',
                        changes: [
                            { field: 'status', before: 'requested', after: 'planned' },
                            { field: 'priority', before: null, after: 'high' },
                            {
                                field: 'product_areas',
                                before: [{ id: '018f47de-7e12-7000-8000-000000000003', name: 'Product analytics' }],
                                after: [
                                    { id: '018f47de-7e12-7000-8000-000000000003', name: 'Product analytics' },
                                    { id: '018f47de-7e12-7000-8000-000000000004', name: 'Data warehouse' },
                                ],
                            },
                        ],
                        is_initial: false,
                        change_source: 'manual',
                        actor_id: 1,
                        actor_name: 'Alex Morgan',
                        changed_at: '2024-01-14T10:00:00Z',
                    },
                    {
                        id: '018f47de-7e12-7000-8000-000000000005',
                        changes: [
                            { field: 'status', before: null, after: 'requested' },
                            { field: 'priority', before: null, after: null },
                            {
                                field: 'accounts',
                                before: [],
                                after: [{ id: '018f47de-7e12-7000-8000-000000000002', name: 'Acme' }],
                            },
                            {
                                field: 'product_areas',
                                before: [],
                                after: [{ id: '018f47de-7e12-7000-8000-000000000003', name: 'Product analytics' }],
                            },
                        ],
                        is_initial: true,
                        change_source: 'manual',
                        actor_id: 1,
                        actor_name: 'Alex Morgan',
                        changed_at: '2024-01-12T10:00:00Z',
                    },
                ],
                'api/projects/:team_id/feature_request_product_areas/': featureRequestStoryItem.product_areas,
                'api/projects/:team_id/accounts/': {
                    count: 3,
                    next: null,
                    previous: null,
                    results: [
                        ...featureRequestStoryItem.account_links.map((link) => link.account),
                        { id: '018f47de-7e12-7000-8000-000000000020', name: 'Initech' },
                    ],
                },
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

export const FeatureRequestDetails: Story = {
    ...FeatureRequests,
    parameters: {
        featureFlags: [FEATURE_FLAGS.CUSTOMER_ANALYTICS, FEATURE_FLAGS.CUSTOMER_ANALYTICS_FEATURE_REQUESTS],
        pageUrl: urls.customerAnalyticsFeatureRequests(featureRequestStoryItem.id),
        testOptions: {
            waitForSelector: '[data-attr="edit-feature-request"]',
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
