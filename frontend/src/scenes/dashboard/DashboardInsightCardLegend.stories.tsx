import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import __dashboard_insight_card_legend_query from './__mocks__/dashboard_insight_card_legend_query.json'

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Dashboards',
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/dashboards/1/': __dashboard_insight_card_legend_query as any,
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-01',
        waitForSelector: '.InsightCard',
        pageUrl: urls.dashboard(1),
    },
    tags: ['test-skip'], // Flakey
}
export default meta

type Story = StoryObj<{}>
export const InsightLegend: Story = {}
