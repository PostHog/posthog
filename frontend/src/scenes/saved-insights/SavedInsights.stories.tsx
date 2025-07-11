import { Meta, StoryObj } from '@storybook/react'
import { App } from 'scenes/App'

import { mswDecorator } from '~/mocks/browser'
import { EMPTY_PAGINATED_RESPONSE, toPaginatedResponse } from '~/mocks/handlers'

import funnelTopToBottom from '../../mocks/fixtures/api/projects/team_id/insights/funnelTopToBottom.json'
import trendsBarBreakdown from '../../mocks/fixtures/api/projects/team_id/insights/trendsBarBreakdown.json'
import trendsPieBreakdown from '../../mocks/fixtures/api/projects/team_id/insights/trendsPieBreakdown.json'
import insightsJson from './__mocks__/insights.json'
import { urls } from 'scenes/urls'

const insights = [trendsBarBreakdown, trendsPieBreakdown, funnelTopToBottom]

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Saved Insights',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-18',
        pageUrl: urls.insights(),
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

type Story = StoryObj<typeof meta>
export const ListView: Story = {}

export const CardView: Story = {
    parameters: {
        pageUrl: `${urls.insights()}?layoutView=card`,
        testOptions: { waitForSelector: '[data-attr=trend-line-graph] > canvas' },
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
