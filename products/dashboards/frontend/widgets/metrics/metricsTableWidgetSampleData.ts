import type { MetricsTableWidgetResult } from './MetricsTableWidget'

const ENDPOINTS: [string, number, number, number][] = [
    ['POST /api/chat', 42.1, 0.38, 1.82],
    ['POST /api/embeddings', 27.4, 0.05, 0.21],
    ['GET /api/traces', 18.9, 0.11, 0.34],
    ['GET /api/generations', 12.3, 0.02, 0.18],
    ['POST /api/evaluations', 6.7, 0.41, 2.65],
    ['GET /api/datasets', 3.2, 0, 0.09],
]

function wave(base: number, seed: number): number[] {
    return Array.from({ length: 30 }, (_, index) => {
        const value = base * (1 + 0.25 * Math.sin((index + seed) / 4) + 0.1 * Math.cos((index * seed) / 3))
        return Math.max(0, Number(value.toFixed(3)))
    })
}

export const metricsTableWidgetSampleResult: MetricsTableWidgetResult = {
    needsConfiguration: false,
    groupBy: 'http.route',
    columns: [
        { label: 'Requests/s', aggregation: 'rate', unit: '1/s' },
        { label: 'Errors/s', aggregation: 'rate', unit: '1/s' },
        { label: 'p95 latency', aggregation: 'histogram_quantile', unit: 's' },
    ],
    rows: ENDPOINTS.map(([key, requests, errors, latency], index) => ({
        key,
        values: [requests, errors || null, latency],
        sparklines: [wave(requests, index + 1), errors ? wave(errors, index + 3) : [], wave(latency, index + 5)],
    })),
    totalCount: 24,
    hasMore: true,
}

const METHOD_VIEWS: [string, string, number, number][] = [
    ['GET', 'detail', 31.4, 0.12],
    ['GET', 'list', 22.8, 0.41],
    ['PATCH', 'detail', 6.1, 0.27],
    ['POST', 'list', 4.9, 0.63],
    ['DELETE', 'detail', 1.2, 0.09],
    ['POST', 'upload', 0.4, 2.35],
]

/** Grouped by two labels, so each row is one combination of an HTTP method and a view. */
export const metricsTableWidgetGroupedSampleResult: MetricsTableWidgetResult = {
    needsConfiguration: false,
    groupBy: ['method', 'view'],
    columns: [
        { label: 'Requests/s', aggregation: 'rate', unit: '1/s' },
        { label: 'p95 latency', aggregation: 'histogram_quantile', unit: 's' },
    ],
    rows: METHOD_VIEWS.map(([method, view, requests, latency], index) => ({
        key: JSON.stringify([method, view]),
        labels: [method, view],
        values: [requests, latency],
        sparklines: [wave(requests, index + 1), wave(latency, index + 5)],
    })),
    totalCount: 6,
    hasMore: false,
}
