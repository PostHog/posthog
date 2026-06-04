import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

const EMPTY_QUERY_RESPONSE = {
    results: [],
    columns: [],
    types: [],
    hogql: '',
    error: null,
    hasMore: false,
    limit: 100,
    offset: 0,
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Marketing Analytics',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-01',
        pageUrl: urls.marketingAnalyticsApp(),
        featureFlags: [FEATURE_FLAGS.WEB_ANALYTICS_MARKETING],
        testOptions: {
            includeNavigationInSnapshot: true,
            waitForLoadersToDisappear: true,
        },
    },
    decorators: [
        mswDecorator({
            get: {
                // No data warehouse sources configured -> the scene shows its onboarding flow
                '/api/environments/:team_id/external_data_sources': () => [200, { count: 0, results: [] }],
                '/api/environments/:team_id/external_data_sources/': () => [200, { count: 0, results: [] }],
            },
            post: {
                '/api/environments/:team_id/query/:kind': (req) => {
                    const queryKind = (req.body as any).query?.kind
                    if (queryKind === 'DatabaseSchemaQuery') {
                        return [200, { tables: {}, joins: [] }]
                    }
                    return [200, EMPTY_QUERY_RESPONSE]
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>
export const MarketingAnalytics: Story = {}

// Snapshot across viewport widths to catch narrow-screen layout regressions in the onboarding flow.
export const MarketingAnalyticsViewports: Story = {
    parameters: {
        testOptions: {
            includeNavigationInSnapshot: true,
            waitForLoadersToDisappear: true,
            viewportWidths: ['narrow', 'medium', 'wide', 'superwide'],
        },
    },
}
