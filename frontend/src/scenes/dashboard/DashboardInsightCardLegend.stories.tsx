import { Meta } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

const meta: Meta = {
    title: 'Scenes-App/Dashboards',
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/dashboards/1/': require('./__mocks__/dashboard_insight_card_legend_query.json'),
                '/api/projects/:team_id/dashboards/2/': require('./__mocks__/dashboard_insight_card_legend_legacy.json'),
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-01',
        waitForSelector: '.InsightCard',
    },
    tags: ['test-skip'], // Flakey
}
export default meta

export const InsightLegend = (): JSX.Element => {
    useEffect(() => {
        router.actions.push(urls.dashboard(1))
    }, [])
    return <App />
}

export const InsightLegendLegacy = (): JSX.Element => {
    useEffect(() => {
        router.actions.push(urls.dashboard(2))
    }, [])
    return <App />
}
