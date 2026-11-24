import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import { EndpointTimeSpent } from './EndpointTimeSpent'
import type { EndpointTimeSpentResponseApi } from './generated/api.schemas'

const WINDOW = { date_from: '2026-06-02T07:00:00Z', date_to: '2026-06-02T08:00:00Z' }

const BREAKDOWN: EndpointTimeSpentResponseApi = {
    components: [
        { name: 'fulfillment-worker', kind: 'service', total_ms: 41_200, avg_ms_per_request: 206, share: 0.46 },
        { name: 'payments', kind: 'service', total_ms: 25_000, avg_ms_per_request: 125, share: 0.28 },
        { name: 'checkout-api', kind: 'service', total_ms: 12_600, avg_ms_per_request: 63, share: 0.14 },
        { name: 'postgresql', kind: 'inferred', total_ms: 7_200, avg_ms_per_request: 36, share: 0.08 },
        { name: 'redis', kind: 'inferred', total_ms: 3_600, avg_ms_per_request: 18, share: 0.04 },
    ],
    request_count: 200,
    avg_duration_ms: 448,
    service: 'checkout-api',
    endpoint: 'POST /orders',
    environment: 'production',
    ...WINDOW,
}

const meta: Meta<typeof EndpointTimeSpent> = {
    title: 'Scenes-App/Application observability/Endpoint time spent',
    component: EndpointTimeSpent,
    args: { service: 'checkout-api', endpoint: 'POST /orders', environment: 'production' },
    parameters: { mockDate: '2026-06-02T08:00:00Z' },
}
export default meta

type Story = StoryObj<typeof EndpointTimeSpent>

export const Breakdown: Story = {
    decorators: [mswDecorator({ get: { '/api/projects/:team/apm/endpoint_time_spent/': BREAKDOWN } })],
    parameters: { testOptions: { waitForSelector: '[data-attr="apm-endpoint-time-spent"]' } },
}

export const NoSampledRequests: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team/apm/endpoint_time_spent/': {
                    ...BREAKDOWN,
                    components: [],
                    request_count: 0,
                    avg_duration_ms: null,
                },
            },
        }),
    ],
}
