import { NodeKind, TrendsQuery, TrendsQueryResponse } from '~/queries/schema/schema-general'

export interface MockResponse {
    match: (query: Record<string, any>) => boolean
    response: TrendsQueryResponse
}

export function buildTrendsQuery(overrides?: Partial<TrendsQuery>): TrendsQuery {
    return {
        kind: NodeKind.TrendsQuery,
        series: [{ kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' }],
        ...overrides,
    }
}

export function buildTrendsResponse(
    series: Array<{
        label: string
        data: number[]
        labels?: string[]
        days?: string[]
        breakdown_value?: string | number
    }>
): TrendsQueryResponse {
    return {
        results: series.map((s) => ({
            action: {
                id: `$${s.label.toLowerCase().replace(/\s+/g, '_')}`,
                type: 'events',
                name: s.label,
            },
            label: s.label,
            count: s.data.reduce((a, b) => a + b, 0),
            data: s.data,
            labels: s.labels ?? s.data.map((_, j) => `Day ${j + 1}`),
            days: s.days ?? s.data.map((_, j) => `2024-01-0${j + 1}`),
            breakdown_value: s.breakdown_value,
        })),
        is_cached: false,
        last_refresh: new Date().toISOString(),
        timings: [],
    }
}

export function matchByKind(kind: string, response: TrendsQueryResponse): MockResponse {
    return {
        match: (query) => query.kind === kind,
        response,
    }
}

export function matchTrends(response: TrendsQueryResponse): MockResponse {
    return matchByKind(NodeKind.TrendsQuery, response)
}
