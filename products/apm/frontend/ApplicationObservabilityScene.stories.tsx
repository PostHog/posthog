import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { APPLICATION_OBSERVABILITY_PATH } from './applicationObservabilityLogic'
import { ApplicationObservabilityScene } from './ApplicationObservabilityScene'
import type { EndpointsHealthResponseApi, ServicesHealthResponseApi } from './generated/api.schemas'

const WINDOW = { date_from: '2026-06-02T07:00:00Z', date_to: '2026-06-02T08:00:00Z' }

const SERVICES: ServicesHealthResponseApi = {
    results: [
        {
            service_name: 'checkout-api',
            environment: 'production',
            status: 'serious',
            health: {
                request_rate: 12.4,
                error_rate: 0.062,
                p95_ms: 840,
                span_count: 44640,
                error_count: 2768,
                apdex: 0.62,
            },
            sparkline: [40, 42, 38, 51, 47, 45, 60, 58, 49, 44, 41, 43],
        },
        {
            service_name: 'payments',
            environment: 'production',
            status: 'good',
            health: {
                request_rate: 4.1,
                error_rate: 0.002,
                p95_ms: 210,
                span_count: 14760,
                error_count: 30,
                apdex: 0.98,
            },
            sparkline: [12, 13, 12, 14, 15, 13, 12, 14, 13, 12, 13, 14],
        },
    ],
    environments: ['production', 'staging'],
    environment: 'production',
    ...WINDOW,
}

const ENDPOINTS: EndpointsHealthResponseApi = {
    results: [
        {
            service_name: 'checkout-api',
            endpoint: 'POST /cart',
            span_name: 'POST /cart',
            route_attribute: null,
            route: null,
            environment: 'production',
            status: 'serious',
            health: {
                request_rate: 6.2,
                error_rate: 0.08,
                p95_ms: 1020,
                span_count: 22320,
                error_count: 1786,
                apdex: 0.62,
            },
        },
        {
            service_name: 'payments',
            endpoint: 'POST /charge',
            span_name: 'POST /charge',
            route_attribute: null,
            route: null,
            environment: 'production',
            status: 'good',
            health: {
                request_rate: 4.1,
                error_rate: 0.002,
                p95_ms: 210,
                span_count: 14760,
                error_count: 30,
                apdex: 0.98,
            },
        },
    ],
    environment: 'production',
    service: null,
    ...WINDOW,
}

const meta: Meta<typeof ApplicationObservabilityScene> = {
    title: 'Scenes-App/Application observability',
    component: ApplicationObservabilityScene,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-06-02T08:00:00Z',
        featureFlags: [
            FEATURE_FLAGS.APPLICATION_OBSERVABILITY,
            FEATURE_FLAGS.PLATFORM_ALERTS,
            FEATURE_FLAGS.PLATFORM_ALERTS_SOURCE_TRACES,
        ],
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team/apm/services/': SERVICES,
                '/api/projects/:team/apm/endpoints/': ENDPOINTS,
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof ApplicationObservabilityScene>

export const ServiceAlertPresets: Story = {
    parameters: {
        pageUrl: APPLICATION_OBSERVABILITY_PATH,
        testOptions: { waitForSelector: '[data-attr="apm-services-alert-p95_latency"]' },
    },
    play: async ({ canvas, userEvent }) => {
        await userEvent.click(await canvas.findByLabelText('More options for checkout-api'))
    },
}

export const EndpointAlertPresets: Story = {
    parameters: {
        pageUrl: `${APPLICATION_OBSERVABILITY_PATH}?tab=endpoints`,
        testOptions: { waitForSelector: '[data-attr="apm-endpoints-alert-error_rate"]' },
    },
    play: async ({ canvas, userEvent }) => {
        await userEvent.click(await canvas.findByLabelText('More options for POST /cart'))
    },
}
