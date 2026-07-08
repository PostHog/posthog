import { useMocks } from '~/mocks/jest'
import { ActorsQueryResponse, NodeKind, TrendsQueryResponse } from '~/queries/schema/schema-general'
import { EventDefinition, PropertyDefinition, RawAnnotationType } from '~/types'

import {
    actionDefinitions,
    eventDefinitions as defaultEventDefs,
    type FunnelStepData,
    funnelTrendsSteps,
    lookupActors,
    lookupCompareSeries,
    lookupFunnelActors,
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
    trendsFilter?: {
        formula?: string
        formulas?: string[]
        formulaNodes?: unknown[]
    }
    [key: string]: unknown
}

function hasFormula(query: QueryBody): boolean {
    const tf = query.trendsFilter
    return !!(tf?.formula || tf?.formulas?.length || tf?.formulaNodes?.length)
}

interface FunnelsQueryResponseLike {
    results: FunnelStepData[]
}

export interface MockResponse {
    match: (query: QueryBody) => boolean
    response:
        | TrendsQueryResponse
        | ActorsQueryResponse
        | FunnelsQueryResponseLike
        | ((query: QueryBody) => TrendsQueryResponse | ActorsQueryResponse | FunnelsQueryResponseLike)
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

// `isFormula` only models the single-formula shape: the real runner combines series per
// formula (`action: null`, `order` = formula index). This mock doesn't combine series, so
// it stamps `order: 0` on every row, which works for a single formula. A future multi-formula
// test would need this to derive the formula index per row (0 for A, 1 for B, …).
function buildTrendsResponse(series: SeriesData[], opts: { isFormula?: boolean } = {}): TrendsQueryResponse {
    return {
        results: series.map((s, i) => {
            const seriesOrder = s.compare || s.breakdown_value != null ? 0 : i
            return {
                action: opts.isFormula
                    ? null
                    : {
                          id: `$${s.label.toLowerCase().replace(/\s+/g, '_')}`,
                          type: 'events',
                          name: s.label,
                          order: seriesOrder,
                      },
                order: opts.isFormula ? 0 : seriesOrder,
                label: s.label,
                count: s.data.reduce((a, b) => a + b, 0),
                aggregated_value: s.data.reduce((a, b) => a + b, 0),
                data: s.data,
                labels: s.labels ?? s.data.map((_, j) => `Day ${j + 1}`),
                days: s.days ?? s.data.map((_, j) => `2024-01-0${j + 1}`),
                breakdown_value: s.breakdown_value,
                compare: s.compare,
                compare_label: s.compare_label,
            }
        }),
    } as TrendsQueryResponse
}

/** Stickiness shares the TrendResult shape with trends, but uses integer-day labels
 *  ("1 day", "2 days", …) and numeric `days` (1, 2, …). The mock reuses the canned
 *  trends series for value diversity and re-keys the x-axis to stickiness form. */
function buildStickinessResponse(series: SeriesData[]): TrendsQueryResponse {
    return {
        results: series.map((s, i) => {
            const buckets = s.data.length
            // Compare current/previous share one series identity (order 0), mirroring the real runner.
            const seriesOrder = s.compare || s.breakdown_value != null ? 0 : i
            return {
                action: {
                    id: `$${s.label.toLowerCase().replace(/\s+/g, '_')}`,
                    type: 'events',
                    name: s.label,
                    order: seriesOrder,
                },
                label: s.label,
                count: s.data.reduce((a, b) => a + b, 0),
                aggregated_value: s.data.reduce((a, b) => a + b, 0),
                data: s.data,
                labels: Array.from({ length: buckets }, (_, j) => `${j + 1} day${j === 0 ? '' : 's'}`),
                days: Array.from({ length: buckets }, (_, j) => j + 1),
                breakdown_value: s.breakdown_value,
                compare: s.compare,
                compare_label: s.compare_label,
            }
        }),
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

/** Funnels in trends-viz mode return a flat `FunnelStep[]` — one entry per series, or per breakdown value. */
function buildFunnelsResponse(query: QueryBody): FunnelsQueryResponseLike {
    const breakdownProp = query.breakdownFilter?.breakdowns?.[0]?.property ?? query.breakdownFilter?.breakdown
    const isCompare = !!(query as { compareFilter?: { compare?: boolean } }).compareFilter?.compare
    if (isCompare && breakdownProp && funnelTrendsSteps.compareByBreakdown[breakdownProp]) {
        return { results: funnelTrendsSteps.compareByBreakdown[breakdownProp] }
    }
    if (breakdownProp && funnelTrendsSteps.byBreakdown[breakdownProp]) {
        return { results: funnelTrendsSteps.byBreakdown[breakdownProp] }
    }
    return { results: [funnelTrendsSteps.default] }
}

interface FunnelsActorsQueryShape {
    kind?: string
    funnelTrendsEntrancePeriodStart?: string | null
    funnelStepBreakdown?: string | number | null
}

// PersonsModalLogic wraps the FunnelsActorsQuery in an ActorsQuery, so the funnel fields
// sit one level deeper at body.source.*.
function isFunnelsActorsQuery(query: QueryBody): boolean {
    const source = (query as { source?: FunnelsActorsQueryShape }).source
    return source?.kind === NodeKind.FunnelsActorsQuery
}

function resolveFunnelActors(query: QueryBody): Array<{ email: string }> {
    const source = (query as { source?: FunnelsActorsQueryShape }).source ?? {}
    // Actors are keyed by calendar date; the query sends a full 'YYYY-MM-DD HH:mm:ss' timestamp.
    const day = source.funnelTrendsEntrancePeriodStart?.split(' ')[0] ?? null
    return lookupFunnelActors({ day, breakdown: source.funnelStepBreakdown ?? null })
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
            response: (query) => buildTrendsResponse(resolveSeriesData(query), { isFormula: hasFormula(query) }),
        },
        {
            match: (query) => query.kind === NodeKind.StickinessQuery,
            response: (query) => buildStickinessResponse(resolveSeriesData(query)),
        },
        {
            match: (query) => query.kind === NodeKind.FunnelsQuery,
            response: (query) => buildFunnelsResponse(query),
        },
        // Must precede the generic ActorsQuery matcher so funnel actor queries route to lookupFunnelActors.
        {
            match: (query) => query.kind === NodeKind.ActorsQuery && isFunnelsActorsQuery(query),
            response: (query) => buildActorsResponse(resolveFunnelActors(query)),
        },
        {
            match: (query) => query.kind === NodeKind.ActorsQuery,
            response: (query) => buildActorsResponse(resolveActors(query)),
        },
    ]
    const responses: MockResponse[] = mockResponses ?? [...(additionalMockResponses ?? []), ...defaults]

    useMocks({
        get: {
            '/api/projects/:team/event_definitions': ({ request }) => {
                const search = new URL(request.url).searchParams.get('search') ?? ''
                const results = filterBySearch(eventDefs, search)
                return [200, { results, count: results.length }]
            },
            '/api/projects/:team/property_definitions': ({ request }) => {
                const search = new URL(request.url).searchParams.get('search') ?? ''
                const results = filterBySearch(propDefs, search)
                return [200, { results, count: results.length }]
            },
            '/api/projects/:team/actions': { results: actionDefinitions },
            '/api/environments/:team/persons/properties': personProperties,
            '/api/environments/:team/sessions/property_definitions': { results: sessionPropertyDefinitions },
            '/api/environments/:team/events/values': ({ request }) => {
                const key = new URL(request.url).searchParams.get('key') ?? ''
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
            '/api/environments/:team_id/query/:kind': async ({ request }) => {
                const queryBody = extractQueryBody(await request.json())

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
