import { StoryObj, StoryFn, Meta } from '@storybook/react'

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

export const ListView: StoryFn = () => {
    useEffect(() => {
        router.actions.push('/insights')
    })
    return <App />
}

export const CardView: StoryObj = {
    render: () => {
        useEffect(() => {
            router.actions.push('/insights?layoutView=card')
        })
        return <App />
    },

    parameters: {
        testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
    },
}

export const EmptyState: StoryFn = () => {
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
