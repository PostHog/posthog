import { RestRequest } from 'msw'

import { useMocks } from '~/mocks/jest'
import { NodeKind, TrendsQueryResponse } from '~/queries/schema/schema-general'
import { EventDefinition, PropertyDefinition } from '~/types'

import { generateData } from './InsightHarness'
import {
    actionDefinitions,
    eventDefinitions as defaultEventDefs,
    personProperties,
    propertyDefinitions as defaultPropDefs,
    propertyValues as defaultPropValues,
    sessionPropertyDefinitions,
} from './test-data'

// ── Types ───────────────────────────────────────────────────────────

export interface QueryBody {
    kind?: string
    series?: Array<{ event?: string; name?: string }>
    breakdownFilter?: {
        breakdowns?: Array<{ property?: string }>
        breakdown?: string
    }
    [key: string]: unknown
}

export interface MockResponse {
    match: (query: QueryBody) => boolean
    response: TrendsQueryResponse | ((query: QueryBody) => TrendsQueryResponse)
}

interface SeriesData {
    label: string
    data: number[]
    labels?: string[]
    days?: string[]
    breakdown_value?: string | number
}

// ── Response builders ───────────────────────────────────────────────

function buildTrendsResponse(series: SeriesData[]): TrendsQueryResponse {
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

function autoRespond(query: QueryBody, propValues: Record<string, string[]>): SeriesData[] {
    const querySeries = query.series ?? []
    const breakdownProp = query.breakdownFilter?.breakdowns?.[0]?.property ?? query.breakdownFilter?.breakdown ?? null
    const breakdownValues = breakdownProp ? (propValues[breakdownProp] ?? []) : []

    if (breakdownValues.length > 0) {
        return querySeries.flatMap((s) =>
            breakdownValues.map((bv) => ({
                label: bv,
                data: generateData(`${s.event ?? s.name}::${bv}`),
                breakdown_value: bv,
            }))
        )
    }

    return querySeries.map((s) => {
        const label = s.name ?? s.event ?? 'Unknown'
        return { label, data: generateData(label) }
    })
}

// ── Filtering helpers ───────────────────────────────────────────────

function filterBySearch<T extends { name: string }>(items: T[], search: string): T[] {
    return search ? items.filter((item) => item.name.includes(search)) : items
}

// ── MSW setup ───────────────────────────────────────────────────────

export interface SetupMocksOptions {
    eventDefinitions?: EventDefinition[]
    propertyDefinitions?: PropertyDefinition[]
    propertyValues?: Record<string, string[]>
    mockResponses?: MockResponse[]
}

// eslint-disable-next-line react-hooks/rules-of-hooks -- useMocks is an MSW helper, not a React hook
export function setupInsightMocks({
    eventDefinitions: eventDefs = defaultEventDefs,
    propertyDefinitions: propDefs = defaultPropDefs,
    propertyValues: propValues = defaultPropValues,
    mockResponses,
}: SetupMocksOptions = {}): void {
    const responses: MockResponse[] = mockResponses ?? [
        {
            match: (query) => query.kind === NodeKind.TrendsQuery,
            response: (query) => buildTrendsResponse(autoRespond(query, propValues)),
        },
    ]

    useMocks({
        get: {
            '/api/projects/:team/event_definitions': (req: RestRequest) => {
                const search = req.url.searchParams.get('search') ?? ''
                const results = filterBySearch(eventDefs, search)
                return [200, { results, count: results.length }]
            },
            '/api/projects/:team/property_definitions': (req: RestRequest) => {
                const search = req.url.searchParams.get('search') ?? ''
                const results = filterBySearch(propDefs, search)
                return [200, { results, count: results.length }]
            },
            '/api/projects/:team/actions': { results: actionDefinitions },
            '/api/environments/:team/persons/properties': personProperties,
            '/api/environments/:team/sessions/property_definitions': { results: sessionPropertyDefinitions },
            '/api/environments/:team/events/values': (req: RestRequest) => {
                const key = req.url.searchParams.get('key') ?? ''
                const values = (propValues[key] ?? []).map((name) => ({ name }))
                return [200, values]
            },
        },
        post: {
            '/api/environments/:team_id/query': (req: RestRequest) => {
                const body = req.body as QueryBody | { query: QueryBody } | null
                const queryBody = (body && 'query' in body ? body.query : body) ?? {}

                for (const mock of responses) {
                    if (mock.match(queryBody as QueryBody)) {
                        const response =
                            typeof mock.response === 'function' ? mock.response(queryBody as QueryBody) : mock.response
                        return [200, response]
                    }
                }

                return [200, { results: [] }]
            },
        },
    })
}
