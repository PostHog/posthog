import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { EMPTY_PAGINATED_RESPONSE, toPaginatedResponse } from '~/mocks/handlers'

import funnelTopToBottom from '../../mocks/fixtures/api/projects/team_id/insights/funnelTopToBottom.json'
import trendsBarBreakdown from '../../mocks/fixtures/api/projects/team_id/insights/trendsBarBreakdown.json'
import trendsPieBreakdown from '../../mocks/fixtures/api/projects/team_id/insights/trendsPieBreakdown.json'
import insightsJson from './__mocks__/insights.json'

const insights = [trendsBarBreakdown, trendsPieBreakdown, funnelTopToBottom]

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Saved Insights',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-18',
        pageUrl: urls.insights(),
        testOptions: { viewport: { width: 1300, height: 2000 } },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/insights': toPaginatedResponse(
                    insightsJson.results.slice(0, 6).map((result, i) => ({
                        // Keep size of response in check
                        ...result,
                        query: insights[i % insights.length].query,
                        result: insights[i % insights.length].result,
                    }))
                ),
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>
export const ListView: Story = {}

export const Home: Story = {
    parameters: {
        featureFlags: { [FEATURE_FLAGS.PRODUCT_ANALYTICS_HOME_TAB]: 'test' },
        pageUrl: `${urls.savedInsights()}?tab=home`,
        testOptions: { viewport: { width: 1300, height: 2000 }, waitForLoadersToDisappear: true },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/insights/my_last_viewed/': [],
                '/api/environments/:team_id/insights/trending/': [],
                '/api/environments/:team_id/insights/activity': EMPTY_PAGINATED_RESPONSE,
                '/api/projects/:team_id/event_definitions/': EMPTY_PAGINATED_RESPONSE,
                '/api/projects/:team_id/insights/': toPaginatedResponse(insightsJson.results.slice(0, 1)),
                '/api/projects/:team_id/alerts/': EMPTY_PAGINATED_RESPONSE,
            },
            post: {
                '/api/environments/:team_id/query/': { results: [] },
                '/api/environments/:team_id/persons/batch_by_distinct_ids/': { results: {} },
            },
        }),
    ],
}

export const HomeWithBooleanFlag: Story = {
    ...Home,
    parameters: {
        ...Home.parameters,
        featureFlags: { [FEATURE_FLAGS.PRODUCT_ANALYTICS_HOME_TAB]: true },
    },
}

export const EmptyState: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/insights': EMPTY_PAGINATED_RESPONSE,
            },
        }),
    ],
}

export const ErrorState: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/insights': () => [500, { detail: 'Internal server error' }],
            },
        }),
    ],
}

export const SearchResults: Story = {
    parameters: {
        pageUrl: urls.savedInsights() + '?search=revenue',
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/insights': toPaginatedResponse(
                    insightsJson.results.slice(0, 5).map((result, i) => {
                        const exactNames = ['Revenue by region', 'Weekly revenue']
                        const similarNames = ['Reveneu trends', 'Q4 reveue', 'Revanue dashboard']
                        const isExact = i < exactNames.length
                        return {
                            ...result,
                            name: isExact ? exactNames[i] : similarNames[i - exactNames.length],
                            query: insights[i % insights.length].query,
                            result: insights[i % insights.length].result,
                            search_match_type: isExact ? 'exact' : 'similar',
                        }
                    })
                ),
            },
        }),
    ],
}
