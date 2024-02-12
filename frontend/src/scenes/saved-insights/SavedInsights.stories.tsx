import { Meta, Story } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { App } from 'scenes/App'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { EMPTY_PAGINATED_RESPONSE, toPaginatedResponse } from '~/mocks/handlers'

import funnelTopToBottom from '../../mocks/fixtures/api/projects/team_id/insights/funnelTopToBottom.json'
import trendsBarBreakdown from '../../mocks/fixtures/api/projects/team_id/insights/trendsBarBreakdown.json'
import trendsPieBreakdown from '../../mocks/fixtures/api/projects/team_id/insights/trendsPieBreakdown.json'
import insightsJson from './__mocks__/insights.json'

const insights = [trendsBarBreakdown, trendsPieBreakdown, funnelTopToBottom]

const meta: Meta = {
    title: 'Scenes-App/Saved Insights',
    parameters: {
        layout: 'fullscreen',
        testOptions: {
            excludeNavigationFromSnapshot: true,
        },
        viewMode: 'story',
        mockDate: '2023-02-18',
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/insights': toPaginatedResponse(
                    insightsJson.results.slice(0, 6).map((result, i) => ({
                        // Keep size of response in check
                        ...result,
                        filters: insights[i % insights.length].filters,
                        result: insights[i % insights.length].result,
                    }))
                ),
            },
        }),
    ],
}
export default meta
export const ListView: Story = () => {
    useEffect(() => {
        router.actions.push('/insights')
    })
    return <App />
}

export const CardView: Story = () => {
    useEffect(() => {
        router.actions.push('/insights?layoutView=card')
    })
    return <App />
}
CardView.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph] > canvas' },
}

export const EmptyState: Story = () => {
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/insights': EMPTY_PAGINATED_RESPONSE,
        },
    })
    useEffect(() => {
        router.actions.push('/insights')
    })
    return <App />
}
