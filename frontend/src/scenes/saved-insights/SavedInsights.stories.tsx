import { Meta, Story } from '@storybook/react'

import { App } from 'scenes/App'
import insightsJson from './__mocks__/insights.json'

import { useEffect } from 'react'
import { router } from 'kea-router'
import { mswDecorator, useStorybookMocks } from '~/mocks/browser'

import trendsBarBreakdown from '../insights/__mocks__/trendsBarBreakdown.json'
import trendsPieBreakdown from '../insights/__mocks__/trendsPieBreakdown.json'
import funnelTopToBottom from '../insights/__mocks__/funnelTopToBottom.json'
import { EMPTY_PAGINATED_RESPONSE, toPaginatedResponse } from '~/mocks/handlers'

const insights = [trendsBarBreakdown, trendsPieBreakdown, funnelTopToBottom]

export default {
    title: 'Scenes-App/Saved Insights',
    parameters: {
        layout: 'fullscreen',
        options: { showPanel: false },
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
} as Meta

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
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
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
