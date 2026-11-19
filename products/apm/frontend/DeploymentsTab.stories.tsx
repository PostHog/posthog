import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'

import { mswDecorator } from '~/mocks/browser'

import type { DeploymentsResponseApi, ServicesHealthResponseApi } from './generated/api.schemas'

const WINDOW = { date_from: '2026-06-02T08:00:00Z', date_to: '2026-06-02T09:00:00Z' }

const health = { request_rate: 12, error_rate: 0.01, p95_ms: 120, span_count: 43200, error_count: 432 }

const servicesHealth: ServicesHealthResponseApi = {
    results: [
        { service_name: 'checkout', environment: 'production', status: 'good', health, sparkline: [] },
        { service_name: 'payments', environment: 'production', status: 'good', health, sparkline: [] },
    ],
    environments: ['production'],
    environment: 'production',
    ...WINDOW,
}

const deployments: DeploymentsResponseApi = {
    results: [
        {
            version: '2.3.0',
            first_seen: '2026-06-02T08:00:00Z',
            last_seen: '2026-06-02T08:20:00Z',
            requests: 14200,
            error_count: 85,
            error_rate: 0.006,
            p95_ms: 118,
            previous_version: null,
            error_rate_change: null,
            p95_change_pct: null,
            active: false,
        },
        {
            version: '2.3.1',
            first_seen: '2026-06-02T08:20:00Z',
            last_seen: '2026-06-02T08:40:00Z',
            requests: 15100,
            error_count: 98,
            error_rate: 0.0065,
            p95_ms: 121,
            previous_version: '2.3.0',
            error_rate_change: 0.0005,
            p95_change_pct: 2.5,
            active: false,
        },
        {
            version: '2.4.0',
            first_seen: '2026-06-02T08:40:00Z',
            last_seen: '2026-06-02T09:00:00Z',
            requests: 13900,
            error_count: 611,
            error_rate: 0.044,
            p95_ms: 342,
            previous_version: '2.3.1',
            error_rate_change: 0.0375,
            p95_change_pct: 182.6,
            active: true,
        },
    ],
    service: 'checkout',
    environment: 'production',
    ...WINDOW,
}

const meta: Meta = {
    component: App,
    title: 'Products/APM/Deployments',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-06-02T09:00:00Z',
        featureFlags: [FEATURE_FLAGS.APPLICATION_OBSERVABILITY],
        pageUrl: '/application-observability?tab=deployments',
        testOptions: { viewport: { width: 1300, height: 700 } },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/apm/services/': servicesHealth,
                '/api/projects/:team_id/apm/deployments/': deployments,
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const VersionsComparedWithTheirPredecessor: Story = {}

export const NoVersions: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/apm/deployments/': { ...deployments, results: [] },
            },
        }),
    ],
}
