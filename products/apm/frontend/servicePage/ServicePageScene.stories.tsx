import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

// A fixed one-hour window, so the charts, totals and timestamps render the same on every run.
const WINDOW_START = Date.parse('2024-01-15T11:00:00Z')
const BUCKET_MS = 5 * 60 * 1000
const BUCKETS = Array.from({ length: 12 }, (_, index) => new Date(WINDOW_START + index * BUCKET_MS).toISOString())

const REQUESTS = [820, 860, 790, 910, 1040, 1210, 1180, 990, 940, 880, 860, 900]
const ERRORS = [4, 6, 3, 5, 18, 42, 37, 9, 6, 5, 4, 6]

// Spans without a message fall back to the exception type, then the HTTP status code, then the span name.
const ERROR_ATTRIBUTES: Record<string, string>[] = [
    { 'exception.message': 'upstream connect error or disconnect/reset before headers' },
    { 'exception.message': 'upstream connect error or disconnect/reset before headers' },
    { 'http.response.status_code': '402' },
    { 'http.response.status_code': '402' },
    { 'http.response.status_code': '402' },
    { 'exception.message': 'payment provider timed out after 5000ms' },
    { 'exception.type': 'CartNotFoundError' },
    {},
]

const dependencyEdge = (
    caller: string,
    callee: string,
    requests: number,
    errorCount: number,
    p95Ms: number,
    kind = 'service',
    inferred = false
): Record<string, unknown> => ({ caller, callee, kind, inferred, requests, error_count: errorCount, p95_ms: p95Ms })

const deploymentVersion = (
    version: string,
    firstSeenMinute: number,
    requests: number,
    errorRate: number,
    p95Ms: number,
    previous: { version: string; errorRate: number; p95Ms: number } | null,
    active: boolean
): Record<string, unknown> => ({
    version,
    first_seen: new Date(WINDOW_START + firstSeenMinute * 60 * 1000).toISOString(),
    last_seen: new Date(WINDOW_START + 59 * 60 * 1000).toISOString(),
    requests,
    error_count: Math.round(requests * errorRate),
    error_rate: errorRate,
    p95_ms: p95Ms,
    previous_version: previous?.version ?? null,
    error_rate_change: previous ? errorRate - previous.errorRate : null,
    p95_change_pct: previous ? ((p95Ms - previous.p95Ms) / previous.p95Ms) * 100 : null,
    active,
})

const endpointRow = (
    endpoint: string,
    status: string,
    requestRate: number,
    errorRate: number,
    p95Ms: number,
    spanCount: number,
    errorCount: number,
    route: string | null = null
): Record<string, unknown> => ({
    service_name: 'checkout',
    endpoint: route ? `${endpoint} ${route}` : endpoint,
    span_name: endpoint,
    route_attribute: route ? 'http.route' : null,
    route,
    environment: 'production',
    status,
    health: {
        request_rate: requestRate,
        error_rate: errorRate,
        p95_ms: p95Ms,
        span_count: spanCount,
        error_count: errorCount,
        apdex: 0.94,
    },
})

const breakdownRows: Record<string, { value: string; count: number; error_count: number }[]> = {
    'deployment.environment.name': [
        { value: 'production', count: 11_000, error_count: 140 },
        { value: 'staging', count: 300, error_count: 2 },
    ],
    'service.version': [
        { value: '2.4.1', count: 9_000, error_count: 120 },
        { value: '2.4.0', count: 2_000, error_count: 20 },
    ],
    'http.response.status_code': [
        { value: '503', count: 96, error_count: 96 },
        { value: '504', count: 31, error_count: 31 },
        { value: '500', count: 18, error_count: 18 },
    ],
}

const meta: Meta = {
    title: 'Scenes-App/Application observability/Service',
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/apm/services/': () => [
                    200,
                    {
                        environment: 'production',
                        environments: ['production', 'staging'],
                        results: [
                            {
                                service_name: 'checkout',
                                environment: 'production',
                                status: 'warning',
                                health: {
                                    request_rate: 3.11,
                                    error_rate: 0.0129,
                                    p95_ms: 186,
                                    span_count: 11_210,
                                    error_count: 145,
                                    apdex: 0.91,
                                },
                                sparkline: REQUESTS,
                            },
                        ],
                    },
                ],
                '/api/projects/:team_id/apm/dependencies/': () => [
                    200,
                    {
                        edges: [
                            dependencyEdge('web', 'checkout', 9_800, 120, 210),
                            dependencyEdge('mobile-api', 'checkout', 1_400, 22, 240),
                            dependencyEdge('checkout', 'payments', 5_100, 96, 180),
                            dependencyEdge('checkout', 'postgresql', 22_400, 3, 8, 'database', true),
                        ],
                        truncated: false,
                        environment: 'production',
                        service: 'checkout',
                    },
                ],
                '/api/projects/:team_id/apm/deployments/': () => [
                    200,
                    {
                        results: [
                            deploymentVersion('2.3.9', 0, 1_200, 0.011, 170, null, false),
                            deploymentVersion(
                                '2.4.0',
                                12,
                                2_000,
                                0.01,
                                176,
                                { version: '2.3.9', errorRate: 0.011, p95Ms: 170 },
                                false
                            ),
                            deploymentVersion(
                                '2.4.1',
                                31,
                                9_000,
                                0.0133,
                                191,
                                { version: '2.4.0', errorRate: 0.01, p95Ms: 176 },
                                true
                            ),
                        ],
                        service: 'checkout',
                        environment: 'production',
                        date_from: new Date(WINDOW_START).toISOString(),
                        date_to: new Date(WINDOW_START + 60 * 60 * 1000).toISOString(),
                    },
                ],
                '/api/projects/:team_id/apm/endpoints/': () => [
                    200,
                    {
                        environment: 'production',
                        environments: ['production', 'staging'],
                        results: [
                            endpointRow('POST', 'serious', 1.42, 0.019, 282, 5_120, 96, '/api/checkout'),
                            endpointRow('GET /api/cart', 'good', 1.17, 0.0074, 77, 4_210, 31),
                            endpointRow('POST /api/cart/items', 'good', 0.4, 0.0084, 99, 1_430, 12),
                            endpointRow('DELETE', 'good', 0.02, 0, 41, 72, 0, '/api/cart/items/:id'),
                        ],
                    },
                ],
            },
            post: {
                '/api/projects/:team_id/file_system/home_folder': () => [200, { id: 'home', path: 'Users/Example' }],
                '/api/:prefix/:team_id/tracing/spans/sparkline/': async ({ request }) => {
                    const { query } = (await request.json()) as { query: { statusCodes?: number[] } }
                    const counts = query.statusCodes?.length ? ERRORS : REQUESTS
                    return [
                        200,
                        {
                            results: BUCKETS.map((time, index) => ({
                                time,
                                service: 'checkout',
                                count: counts[index],
                            })),
                        },
                    ]
                },
                '/api/:prefix/:team_id/tracing/spans/latency_percentiles/': () => [
                    200,
                    {
                        results: BUCKETS.map((time, index) => ({
                            time,
                            count: REQUESTS[index],
                            p50_ns: (38 + (index % 3)) * 1_000_000,
                            p95_ns: (index === 5 ? 412 : 176 + index * 3) * 1_000_000,
                            p99_ns: (index === 5 ? 780 : 320 + index * 5) * 1_000_000,
                        })),
                    },
                ],
                '/api/:prefix/:team_id/tracing/spans/attribute-breakdown/': async ({ request }) => {
                    const { query } = (await request.json()) as { query: { breakdownKey: string } }
                    const rows = (breakdownRows[query.breakdownKey] ?? []).map((row) => ({
                        ...row,
                        p50_duration_nano: 1,
                        p95_duration_nano: 1,
                    }))
                    return [200, { results: rows, compare: null }]
                },
                '/api/:prefix/:team_id/tracing/spans/query/': () => [
                    200,
                    {
                        hasMore: false,
                        results: ERROR_ATTRIBUTES.map((attributes, index) => ({
                            uuid: `uuid-${index}`,
                            trace_id: `A1B2C3D4E5F60718293A4B5C6D7E8F9${index}`,
                            span_id: `1A2B3C4D5E6F708${index}`,
                            parent_span_id: '',
                            name: 'POST /api/checkout',
                            kind: 2,
                            service_name: 'checkout',
                            status_code: 2,
                            timestamp: new Date(WINDOW_START + (55 - index * 6) * 60 * 1000).toISOString(),
                            end_time: new Date(WINDOW_START + (55 - index * 6) * 60 * 1000 + 300).toISOString(),
                            duration_nano: 300_000_000,
                            is_root_span: true,
                            matched_filter: true,
                            attributes,
                            resource_attributes: {},
                        })),
                    },
                ],
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2024-01-15 12:00:00',
        featureFlags: [FEATURE_FLAGS.APPLICATION_OBSERVABILITY],
        pageUrl: urls.applicationObservabilityService('checkout', { environment: 'production' }),
        testOptions: {
            // Each exists only once its own response has arrived.
            waitForSelector: [
                '[data-attr="apm-service-health"]',
                '[data-attr="apm-service-error-trace-link"]',
                '[data-attr="apm-service-status-code-errors"]',
                'text=POST /api/cart/items',
                '[data-attr="apm-service-dependencies-downstream"] >> text=payments',
                '[data-attr="apm-service-deployments-table"] >> text=2.4.1',
            ],
        },
    },
}
export default meta

type Story = StoryObj<{}>

export const ServicePage: Story = {
    render: () => <App />,
}
