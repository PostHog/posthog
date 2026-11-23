import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { APPLICATION_OBSERVABILITY_PATH } from './applicationObservabilityLogic'
import { ApplicationObservabilityScene } from './ApplicationObservabilityScene'
import type {
    EndpointsHealthResponseApi,
    HealthRowApi,
    HealthStatusEnumApi,
    ServiceHealthApi,
    ServicesHealthResponseApi,
} from './generated/api.schemas'

const WINDOW = { date_from: '2026-06-02T07:00:00Z', date_to: '2026-06-02T08:00:00Z' }

function health(request_rate: number, error_rate: number, p95_ms: number, apdex: number | null): HealthRowApi {
    const span_count = Math.round(request_rate * 3600)
    return { request_rate, error_rate, p95_ms, span_count, error_count: Math.round(span_count * error_rate), apdex }
}

function service(service_name: string, status: HealthStatusEnumApi, row: HealthRowApi): ServiceHealthApi {
    return { service_name, environment: 'production', status, health: row, sparkline: [12, 14, 13, 15, 16, 14] }
}

const SERVICES: ServicesHealthResponseApi = {
    results: [
        service('checkout-api', 'serious', health(12.4, 0.062, 1840, 0.61)),
        service('search', 'good', health(18.4, 0.004, 711, 0.83)),
        service('payments', 'good', health(4.1, 0.002, 210, 0.99)),
    ],
    environments: ['production'],
    environment: 'production',
    ...WINDOW,
}

const ENDPOINTS: EndpointsHealthResponseApi = {
    results: [
        {
            service_name: 'checkout-api',
            endpoint: 'POST /checkout',
            span_name: 'POST /checkout',
            route_attribute: null,
            route: null,
            environment: 'production',
            status: 'serious',
            health: health(6.2, 0.08, 2300, 0.48),
        },
        {
            service_name: 'search',
            endpoint: 'GET /search',
            span_name: 'GET /search',
            route_attribute: null,
            route: null,
            environment: 'production',
            status: 'good',
            health: health(18.4, 0.004, 711, 0.83),
        },
    ],
    environment: 'production',
    service: null,
    ...WINDOW,
}

const meta: Meta<typeof ApplicationObservabilityScene> = {
    title: 'Scenes-App/Application observability/Apdex',
    component: ApplicationObservabilityScene,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-06-02T08:00:00Z',
        featureFlags: [FEATURE_FLAGS.APPLICATION_OBSERVABILITY],
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

export const ServicesApdex: Story = {
    parameters: {
        pageUrl: APPLICATION_OBSERVABILITY_PATH,
        testOptions: { waitForSelector: '[data-attr="apm-services-table"] tbody tr' },
    },
}

export const EndpointsApdex: Story = {
    parameters: {
        pageUrl: `${APPLICATION_OBSERVABILITY_PATH}?tab=endpoints`,
        testOptions: { waitForSelector: '[data-attr="apm-endpoints-table"] tbody tr' },
    },
}
