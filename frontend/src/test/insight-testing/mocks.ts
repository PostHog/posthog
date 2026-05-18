import { RestRequest } from 'msw'

import { useMocks } from '~/mocks/jest'
import { ActorsQueryResponse, NodeKind, TrendsQueryResponse } from '~/queries/schema/schema-general'
import { EventDefinition, PropertyDefinition, RawAnnotationType } from '~/types'

import {
    actionDefinitions,
    eventDefinitions as defaultEventDefs,
    lookupActors,
    lookupCompareSeries,
    lookupSeries,
    personProperties,
    propertyDefinitions as defaultPropDefs,
    propertyValues as defaultPropValues,
    sessionPropertyDefinitions,
    type SeriesData,
} from './test-data'

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
    response:
        | TrendsQueryResponse
        | ActorsQueryResponse
        | ((query: QueryBody) => TrendsQueryResponse | ActorsQueryResponse)
}

/** Build an ActorsQueryResponse shaped like the server response, with one row
 *  per canned person. Each person's display name is driven by the email
 *  property (see `asDisplay` in scenes/persons/person-utils). */
export function buildActorsResponse(
    persons: Array<{ email: string; id?: string; distinctId?: string }>
): ActorsQueryResponse {
    return {
        results: persons.map((p, i) => [
            {
                id: p.id ?? `person-${i}`,
                distinct_ids: [p.distinctId ?? `distinct-${i}`],
                is_identified: true,
                properties: { email: p.email },
                created_at: '2024-06-10T00:00:00Z',
            },
        ]),
        columns: ['actor'],
        hogql: '',
        limit: 100,
        offset: 0,
    } as ActorsQueryResponse
}

function buildTrendsResponse(series: SeriesData[]): TrendsQueryResponse {
    return {
        results: series.map((s, i) => ({
            action: {
                id: `$${s.label.toLowerCase().replace(/\s+/g, '_')}`,
                type: 'events',
                name: s.label,
                order: s.compare ? 0 : i,
            },
            label: s.label,
            count: s.data.reduce((a, b) => a + b, 0),
            aggregated_value: s.data.reduce((a, b) => a + b, 0),
            data: s.data,
            labels: s.labels ?? s.data.map((_, j) => `Day ${j + 1}`),
            days: s.days ?? s.data.map((_, j) => `2024-01-0${j + 1}`),
            breakdown_value: s.breakdown_value,
            compare: s.compare,
            compare_label: s.compare_label,
        })),
    } as TrendsQueryResponse
}

/** Pull the bits of an ActorsQuery we use to look up canned actors. */
interface ActorsQueryBodyShape {
    source?: {
        source?: { series?: Array<{ event?: string }> }
        breakdown?: string | number | null
        day?: string | number | null
    }
}

function resolveActors(query: QueryBody): Array<{ email: string }> {
    const body = query as ActorsQueryBodyShape
    const insightSource = body.source
    return lookupActors({
        event: insightSource?.source?.series?.[0]?.event,
        breakdown: insightSource?.breakdown,
        day: insightSource?.day,
    })
}

function resolveSeriesData(query: QueryBody): SeriesData[] {
    const breakdownProp = query.breakdownFilter?.breakdowns?.[0]?.property ?? query.breakdownFilter?.breakdown ?? null
    const isCompare = !!(query as Record<string, unknown>).compareFilter

    return (query.series ?? []).flatMap((s) => {
        const eventName = s.event ?? s.name ?? 'Unknown'
        if (isCompare) {
            const compareSeries = lookupCompareSeries(eventName)
            if (compareSeries) {
                return compareSeries
            }
        }
        return lookupSeries(eventName, breakdownProp ?? undefined)
    })
}

function filterBySearch<T extends { name: string }>(items: T[], search: string): T[] {
    return search ? items.filter((item) => item.name.includes(search)) : items
}

function extractQueryBody(body: unknown): QueryBody {
    if (body && typeof body === 'object' && 'query' in body) {
        return (body as { query: QueryBody }).query
    }
    return (body as QueryBody) ?? {}
}

export interface SetupMocksOptions {
    eventDefinitions?: EventDefinition[]
    propertyDefinitions?: PropertyDefinition[]
    propertyValues?: Record<string, string[]>
    /** Fully replace the default TrendsQuery + ActorsQuery responses. */
    mockResponses?: MockResponse[]
    /** Prepend extra matchers to the default response chain. Useful when a
     *  test wants to intercept one query kind (e.g. capture the ActorsQuery
     *  body) without losing the default mocks for the others. */
    additionalMockResponses?: MockResponse[]
    /** Annotations returned by `/annotations/`. Defaults to []. */
    annotations?: RawAnnotationType[]
}

// eslint-disable-next-line react-hooks/rules-of-hooks -- useMocks is an MSW helper, not a React hook
export function setupInsightMocks({
    eventDefinitions: eventDefs = defaultEventDefs,
    propertyDefinitions: propDefs = defaultPropDefs,
    propertyValues: propValues = defaultPropValues,
    mockResponses,
    additionalMockResponses,
    annotations = [],
}: SetupMocksOptions = {}): void {
    const defaults: MockResponse[] = [
        {
            match: (query) => query.kind === NodeKind.TrendsQuery,
            response: (query) => buildTrendsResponse(resolveSeriesData(query)),
        },
        {
            match: (query) => query.kind === NodeKind.ActorsQuery,
            response: (query) => buildActorsResponse(resolveActors(query)),
        },
    ]
    const responses: MockResponse[] = mockResponses ?? [...(additionalMockResponses ?? []), ...defaults]

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
            // TODO: support loading saved insights — accept a savedInsights option in SetupMocksOptions
            // and return them here, enabling tests that load insights by short ID
            '/api/environments/:team_id/insights/': { results: [] },
            '/api/environments/:team_id/insights/trend': [],
            // Annotations layer fetches this on mount; resolve immediately so async
            // state changes don't race against tooltip/click assertions.
            '/api/projects/:team_id/annotations/': {
                results: annotations,
                count: annotations.length,
                next: null,
                previous: null,
            },
        },
        post: {
            '/api/environments/:team_id/query/:kind': (req: RestRequest) => {
                const queryBody = extractQueryBody(req.body)

                for (const mock of responses) {
                    if (mock.match(queryBody)) {
                        const response = typeof mock.response === 'function' ? mock.response(queryBody) : mock.response
                        return [200, response]
                    }
                }

                return [200, { results: [] }]
            },
        },
    })
}
