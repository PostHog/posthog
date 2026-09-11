import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import coverageSnapshot from '../../../../../posthog/data/grafana_metrics_coverage.json'

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Instance/MetricsMigration',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-09-11',
        pageUrl: urls.instanceMetricsMigration(),
        testOptions: { viewport: { width: 1400, height: 1100 } },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/instance_status/metrics_migration': [200, { results: coverageSnapshot }],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const MetricsMigration: Story = {}
