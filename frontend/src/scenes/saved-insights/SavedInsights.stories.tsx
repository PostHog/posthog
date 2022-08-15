import { Meta } from '@storybook/react'

import { App } from 'scenes/App'
import insightsJson from './__mocks__/insights.json'

import React, { useEffect } from 'react'
import { router } from 'kea-router'
import { mswDecorator } from '~/mocks/browser'

import trendsBarBreakdown from '../insights/__mocks__/trendsBarBreakdown.json'
import trendsPieBreakdown from '../insights/__mocks__/trendsPieBreakdown.json'
import funnelTopToBottom from '../insights/__mocks__/funnelTopToBottom.json'

const insights = [trendsBarBreakdown, trendsPieBreakdown, funnelTopToBottom]

export default {
    title: 'Scenes-App/Saved Insights',
    parameters: { layout: 'fullscreen', options: { showPanel: false }, viewMode: 'story' },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:projectId/insights': {
                    ...insightsJson,
                    results: insightsJson.results.map((result, i) => ({
                        ...result,
                        filters: insights[i % insights.length].filters,
                        result: insights[i % insights.length].result,
                    })),
                },
            },
        }),
    ],
} as Meta

export const ListView = (): JSX.Element => {
    useEffect(() => {
        router.actions.push('/insights')
    })
    return <App />
}

export const CardView = (): JSX.Element => {
    useEffect(() => {
        router.actions.push('/insights?layoutView=card')
    })
    return <App />
}
