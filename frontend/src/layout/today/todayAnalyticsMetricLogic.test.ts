import type { InsightApi } from 'products/product_analytics/frontend/generated/api.schemas'

import { metricFromInsight } from './todayAnalyticsMetricLogic'

const insight = (query: unknown, result: unknown): InsightApi => ({ query, result }) as unknown as InsightApi
const trends = (trendsFilter?: Record<string, unknown>): unknown => ({
    kind: 'InsightVizNode',
    source: { kind: 'TrendsQuery', series: [], trendsFilter },
})
const SERIES = [{ count: 60, data: [10, 20, 30], labels: ['Mon', 'Tue', 'Wed'] }]

describe('metricFromInsight', () => {
    test.each([
        ['the total by default', insight(trends(), SERIES), 60],
        ['the latest point when the insight asks for it', insight(trends({ metricSummary: 'latest' }), SERIES), 30],
        ['the average when the insight asks for it', insight(trends({ metricSummary: 'average' }), SERIES), 20],
        ['no number for a funnel', insight({ kind: 'InsightVizNode', source: { kind: 'FunnelsQuery' } }, SERIES), null],
        ['no number before the first result', insight(trends(), null), null],
    ])('shows %s', (_name, given, expected) => {
        expect(metricFromInsight(given)?.value ?? null).toEqual(expected)
    })
})
