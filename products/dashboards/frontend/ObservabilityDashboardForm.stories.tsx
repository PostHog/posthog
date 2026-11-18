import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { ObservabilityDashboardForm } from './ObservabilityDashboardForm'

const meta: Meta<typeof ObservabilityDashboardForm> = {
    title: 'Products/Dashboards/Observability dashboard form',
    component: ObservabilityDashboardForm,
    parameters: {
        featureFlags: [FEATURE_FLAGS.METRICS, FEATURE_FLAGS.METRICS_INSIGHT_BUILDER],
        testOptions: { waitForSelector: '[data-attr="metrics-starter-dashboard-metrics"]' },
    },
    args: { onClose: () => {} },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/metrics/names/': {
                    results: [
                        { name: 'http_requests_total', metric_type: 'sum' },
                        { name: 'http_request_duration_seconds', metric_type: 'histogram' },
                    ],
                },
                '/api/environments/:team_id/metrics/attribute_values/': {
                    results: [{ id: 'example-api', name: 'example-api', count: 1 }],
                },
            },
        }),
    ],
}
export default meta
type Story = StoryObj<typeof ObservabilityDashboardForm>
export const ServiceStarter: Story = {}
