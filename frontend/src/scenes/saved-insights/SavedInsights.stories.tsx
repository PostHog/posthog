import { Meta } from '@storybook/react'

import { SavedInsights } from './SavedInsights'
import insightsJson from './__mocks__/insights.json'

import React, { useEffect } from 'react'
import { router } from 'kea-router'
import { mswDecorator } from '~/mocks/browser'

import trendsBarBreakdown from '../insights/__mocks__/trendsBarBreakdown.json'
import trendsPieBreakdown from '../insights/__mocks__/trendsPieBreakdown.json'
import funnelTopToBottom from '../insights/__mocks__/funnelTopToBottom.json'

const insights = [trendsBarBreakdown, trendsPieBreakdown, funnelTopToBottom]

export default {
    title: 'Scenes/Saved Insights',
    parameters: { options: { showPanel: false }, viewMode: 'canvas' },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/1/insights': {
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
    return <SavedInsights />
}

export const CardView = (): JSX.Element => {
    useEffect(() => {
        router.actions.push('/insights?layoutView=card')
    })
    return <SavedInsights />
}
