import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'

import { mswDecorator } from '~/mocks/browser'

import type { DependenciesResponseApi, ServicesHealthResponseApi } from './generated/api.schemas'

const WINDOW = { date_from: '2026-06-02T08:00:00Z', date_to: '2026-06-02T09:00:00Z' }

const servicesHealth: ServicesHealthResponseApi = {
    results: [],
    environments: ['production'],
    environment: 'production',
    ...WINDOW,
}

const dependencies: DependenciesResponseApi = {
    edges: [
        {
            caller: 'frontend',
            callee: 'checkout',
            inferred: false,
            kind: 'service',
            requests: 9120,
            error_count: 41,
            p95_ms: 182,
        },
        {
            caller: 'frontend',
            callee: 'catalog',
            inferred: false,
            kind: 'service',
            requests: 18400,
            error_count: 9,
            p95_ms: 38,
        },
        {
            caller: 'checkout',
            callee: 'payments',
            inferred: false,
            kind: 'service',
            requests: 1830,
            error_count: 112,
            p95_ms: 640,
        },
        {
            caller: 'checkout',
            callee: 'postgresql:orders',
            inferred: true,
            kind: 'database',
            requests: 7300,
            error_count: 0,
            p95_ms: 12,
        },
        {
            caller: 'checkout',
            callee: 'kafka:order-events',
            inferred: true,
            kind: 'queue',
            requests: 1810,
            error_count: 0,
            p95_ms: 4,
        },
        {
            caller: 'catalog',
            callee: 'redis',
            inferred: true,
            kind: 'database',
            requests: 36100,
            error_count: 2,
            p95_ms: 1,
        },
        {
            caller: 'payments',
            callee: 'api.payments.example.com',
            inferred: true,
            kind: 'external',
            requests: 1790,
            error_count: 98,
            p95_ms: 710,
        },
    ],
    truncated: false,
    sampled: false,
    trace_count: 4,
    environment: 'production',
    service: null,
    ...WINDOW,
}

const meta: Meta = {
    component: App,
    title: 'Products/APM/Dependencies',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-06-02T09:00:00Z',
        featureFlags: [FEATURE_FLAGS.APPLICATION_OBSERVABILITY],
        pageUrl: '/application-observability?tab=dependencies',
        testOptions: { viewport: { width: 1300, height: 1100 } },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/apm/services/': servicesHealth,
                '/api/projects/:team_id/apm/dependencies/': dependencies,
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const AllServices: Story = {}

export const Empty: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/apm/dependencies/': { ...dependencies, edges: [] },
            },
        }),
    ],
}

const manyCalls: DependenciesResponseApi = {
    ...dependencies,
    edges: [
        ...Array.from({ length: 48 }, (_, i) => ({
            caller: `service-${i % 8}`,
            callee: `service-${(i % 8) + 1 + Math.floor(i / 8)}`,
            inferred: false,
            kind: 'service' as const,
            requests: 1000 + i * 37,
            error_count: i % 7 === 0 ? 120 : 0,
            p95_ms: 20 + i,
        })),
        ...Array.from({ length: 12 }, (_, i) => ({
            caller: 'service-0',
            callee: `api${i}.example.com`,
            inferred: true,
            kind: 'external' as const,
            requests: 400 + i * 50,
            error_count: i,
            p95_ms: 90 + i * 15,
        })),
    ],
}

export const AllServicesCapped: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/apm/dependencies/': manyCalls,
            },
        }),
    ],
}

export const Sampled: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/apm/dependencies/': { ...dependencies, sampled: true, trace_count: 2000 },
            },
        }),
    ],
}

const healthRow = (service_name: string): ServicesHealthResponseApi['results'][number] => ({
    service_name,
    environment: 'production',
    status: 'good',
    health: { request_rate: 1, error_rate: 0, p95_ms: 10, span_count: 1, error_count: 0, apdex: 1 },
    sparkline: [1],
})

export const TooManySpans: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/apm/services/': {
                    ...servicesHealth,
                    results: ['checkout', 'frontend', 'payments'].map(healthRow),
                },
                '/api/projects/:team_id/apm/dependencies/': [
                    400,
                    { detail: 'This window reads too many spans. Pick a shorter window or one service.' },
                ],
            },
        }),
    ],
}
