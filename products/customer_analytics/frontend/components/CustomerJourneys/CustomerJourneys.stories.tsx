import { Meta, StoryFn } from '@storybook/react'

import { App } from 'scenes/App'
import { emptyJourneysList, JOURNEY_FEATURE_FLAGS } from 'scenes/funnels/FunnelFlowGraph/__mocks__/journeyMocks'
import { urls } from 'scenes/urls'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Customer Analytics/Journeys',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2024-01-15',
        featureFlags: JOURNEY_FEATURE_FLAGS,
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

export const EmptyState: StoryFn = () => {
    useStorybookMocks({
        get: { 'api/environments/:team_id/customer_journeys/': emptyJourneysList },
    })
    return <App />
}
EmptyState.parameters = {
    pageUrl: urls.customerAnalyticsJourneys(),
    testOptions: { waitForSelector: '[data-attr="product-introduction-journey"]' },
}
