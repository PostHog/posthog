import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { APPLICATION_OBSERVABILITY_PATH } from './applicationObservabilityLogic'
import { ApplicationObservabilityScene } from './ApplicationObservabilityScene'
import type {
    EndpointHealthApi,
    EndpointsHealthResponseApi,
    HealthRowApi,
    HealthStatusEnumApi,
    ServiceHealthApi,
    ServicesHealthResponseApi,
} from './generated/api.schemas'

const WINDOW = { date_from: '2026-06-02T07:00:00Z', date_to: '2026-06-02T08:00:00Z' }

function health(request_rate: number, error_rate: number, p95_ms: number | null): HealthRowApi {
    const span_count = Math.round(request_rate * 3600)
    return { request_rate, error_rate, p95_ms, span_count, error_count: Math.round(span_count * error_rate) }
}

function service(service_name: string, status: HealthStatusEnumApi, row: HealthRowApi): ServiceHealthApi {
    return {
        service_name,
        environment: 'production',
        status,
        health: row,
        sparkline: [40, 42, 38, 51, 47, 45, 60, 58, 49, 44, 41, 43],
    }
}

function endpoint(
    service_name: string,
    name: string,
    status: HealthStatusEnumApi,
    row: HealthRowApi
): EndpointHealthApi {
    return { service_name, endpoint: name, environment: 'production', status, health: row }
}

const SERVICES: ServicesHealthResponseApi = {
    results: [
        service('checkout-api', 'serious', health(12.4, 0.081, 840)),
        service('inventory-worker', 'warning', health(0.5, 0.028, 365)),
        service('storefront', 'good', health(26.1, 0.0034, 190)),
        service('payments', 'good', health(4.1, 0.002, 210)),
        service('nightly-export', 'good', health(0.01, 0, null)),
    ],
    environments: ['production', 'staging'],
    environment: 'production',
    ...WINDOW,
}

const ENDPOINTS: EndpointsHealthResponseApi = {
    results: [
        endpoint('checkout-api', 'POST /cart', 'serious', health(6.2, 0.094, 1020)),
        endpoint('checkout-api', 'POST /checkout', 'warning', health(3.1, 0.0158, 640)),
        endpoint('checkout-api', 'GET /cart', 'good', health(3.1, 0.001, 88)),
        endpoint('storefront', 'GET /search', 'good', health(18.4, 0.004, 711)),
        endpoint('payments', 'POST /charge', 'good', health(4.1, 0.002, 210)),
    ],
    environment: 'production',
    service: null,
    ...WINDOW,
}

const meta: Meta<typeof ApplicationObservabilityScene> = {
    title: 'Scenes-App/Application observability/Health tables',
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

export const ServicesWithErrorRateBars: Story = {
    parameters: {
        pageUrl: APPLICATION_OBSERVABILITY_PATH,
        testOptions: { waitForSelector: '[data-attr="apm-services-table"] tbody tr' },
    },
}

export const EndpointsFilteredBySearch: Story = {
    parameters: {
        pageUrl: `${APPLICATION_OBSERVABILITY_PATH}?tab=endpoints&search=cart`,
        testOptions: { waitForSelector: '[data-attr="apm-endpoints-table"] tbody tr' },
    },
}
