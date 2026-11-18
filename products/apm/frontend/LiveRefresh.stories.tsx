import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { APPLICATION_OBSERVABILITY_PATH } from './applicationObservabilityLogic'
import { ApplicationObservabilityScene } from './ApplicationObservabilityScene'
import type { ServicesHealthResponseApi } from './generated/api.schemas'

const SERVICES: ServicesHealthResponseApi = {
    results: [
        {
            service_name: 'checkout-api',
            environment: 'production',
            status: 'warning',
            health: { request_rate: 12.4, error_rate: 0.021, p95_ms: 840, span_count: 44640, error_count: 937 },
            sparkline: [40, 42, 38, 51, 47, 45, 60, 58, 49, 44, 41, 43],
        },
    ],
    environments: ['production'],
    environment: 'production',
    date_from: '2026-06-02T07:00:00Z',
    date_to: '2026-06-02T08:00:00Z',
}

const meta: Meta<typeof ApplicationObservabilityScene> = {
    title: 'Scenes-App/Application observability/Live refresh',
    component: ApplicationObservabilityScene,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-06-02T08:00:00Z',
        featureFlags: [FEATURE_FLAGS.APPLICATION_OBSERVABILITY],
    },
    decorators: [mswDecorator({ get: { '/api/projects/:team/apm/services/': SERVICES } })],
}
export default meta

type Story = StoryObj<typeof ApplicationObservabilityScene>

export const Live: Story = {
    parameters: {
        pageUrl: APPLICATION_OBSERVABILITY_PATH,
        testOptions: { waitForSelector: '[data-attr="apm-services-table"] tbody tr' },
    },
}

export const Paused: Story = {
    parameters: {
        pageUrl: `${APPLICATION_OBSERVABILITY_PATH}?paused=true`,
        testOptions: { waitForSelector: '[data-attr="apm-services-table"] tbody tr' },
    },
}
