import { EventDefinition, PropertyDefinition, PropertyType } from '~/types'

const friday = '2024-06-14T16:00:00.000Z'
const setupWeek = '2024-06-03T10:00:00.000Z'

const days = ['2024-06-10', '2024-06-11', '2024-06-12', '2024-06-13', '2024-06-14']
const labels = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']

export const eventDefinitions: EventDefinition[] = [
    {
        id: 'evt-001',
        name: '$pageview',
        description: 'Scoreboard website viewed',
        tags: ['web'],
        last_seen_at: friday,
        created_at: setupWeek,
    },
    {
        id: 'evt-002',
        name: 'Napped',
        description: 'A hedgehog took a nap',
        tags: ['nap'],
        last_seen_at: friday,
        created_at: setupWeek,
    },
    {
        id: 'evt-003',
        name: 'ZeroCounts',
        description: 'Event with one empty and one active series',
        tags: [],
        last_seen_at: friday,
        created_at: setupWeek,
    },
    {
        id: 'evt-004',
        name: 'Minimal',
        description: 'Event with no action metadata',
        tags: [],
        last_seen_at: friday,
        created_at: setupWeek,
    },
    {
        id: 'evt-005',
        name: 'NoActivity',
        description: 'Event whose series is all zeros (drives empty-state branch)',
        tags: [],
        last_seen_at: friday,
        created_at: setupWeek,
    },
]

export const propertyDefinitions: PropertyDefinition[] = [
    {
        id: 'prop-101',
        name: 'hedgehog',
        description: 'Name of the hedgehog',
        tags: [],
        is_numerical: false,
        property_type: PropertyType.String,
    },
]

export const propertyValues: Record<string, string[]> = {
    hedgehog: ['Spike', 'Bramble', 'Thistle', 'Conker', 'Prickles'],
}

export const personProperties = [
    { id: 1, name: 'email', count: 30 },
    { id: 2, name: 'name', count: 30 },
]

export const sessionPropertyDefinitions: PropertyDefinition[] = [
    {
        id: 'session-001',
        name: '$session_duration',
        description: 'Duration of the session in seconds',
        is_numerical: true,
        property_type: PropertyType.Numeric,
    },
]

export const actionDefinitions: object[] = []

export interface SeriesData {
    label: string
    data: number[]
    labels?: string[]
    days?: string[]
    breakdown_value?: string | number
    compare?: boolean
    compare_label?: string
}

type CannedSeries = SeriesData & { labels: string[]; days: string[] }

export const trendsSeries = {
    pageviews: {
        label: '$pageview',
        data: [45, 82, 134, 210, 95],
        days,
        labels,
    } satisfies CannedSeries,
    napped: {
        label: 'Napped',
        data: [1, 3, 5, 8, 2],
        days,
        labels,
    } satisfies CannedSeries,
    napsByHedgehog: [
        { label: 'Spike', data: [1, 2, 3, 4, 1], days, labels, breakdown_value: 'Spike' },
        { label: 'Bramble', data: [0, 0, 1, 1, 0], days, labels, breakdown_value: 'Bramble' },
        { label: 'Thistle', data: [0, 1, 0, 2, 1], days, labels, breakdown_value: 'Thistle' },
        { label: 'Conker', data: [0, 0, 0, 0, 0], days, labels, breakdown_value: 'Conker' },
        { label: 'Prickles', data: [0, 0, 1, 1, 0], days, labels, breakdown_value: 'Prickles' },
    ] satisfies CannedSeries[],
    withZeroCounts: [
        { label: 'EmptySeries', data: [0, 0, 0, 0, 0], days, labels },
        { label: 'ActiveSeries', data: [1, 2, 3, 2, 2], days, labels },
    ] satisfies CannedSeries[],
    minimal: {
        label: 'Minimal',
        data: [1, 1, 1, 1, 1],
        days,
        labels,
    } satisfies CannedSeries,
    noActivity: {
        label: 'NoActivity',
        data: [0, 0, 0, 0, 0],
        days,
        labels,
    } satisfies CannedSeries,
    pageviewsCompare: [
        { label: '$pageview', data: [45, 82, 134, 210, 95], days, labels, compare: true, compare_label: 'current' },
        {
            label: '$pageview',
            data: [30, 60, 100, 180, 70],
            days: ['2024-06-03', '2024-06-04', '2024-06-05', '2024-06-06', '2024-06-07'],
            labels,
            compare: true,
            compare_label: 'previous',
        },
    ] satisfies CannedSeries[],
}

// Maps (event name, optional breakdown) → canned series data.
// The mock query handler calls this to resolve a query into response data.

interface EventSeriesConfig {
    default: SeriesData
    /** Return multiple series for this event even without a breakdown. */
    multi?: SeriesData[]
    breakdowns?: Record<string, SeriesData[]>
}

const seriesByEvent: Record<string, EventSeriesConfig> = {
    $pageview: { default: trendsSeries.pageviews },
    Napped: {
        default: trendsSeries.napped,
        breakdowns: {
            hedgehog: trendsSeries.napsByHedgehog,
        },
    },
    ZeroCounts: { default: trendsSeries.withZeroCounts[0], multi: trendsSeries.withZeroCounts },
    Minimal: { default: trendsSeries.minimal },
    NoActivity: { default: trendsSeries.noActivity },
}

/** Resolver for compare queries — returns current + previous period series. */
export function lookupCompareSeries(eventName: string): SeriesData[] | null {
    if (eventName === '$pageview') {
        return trendsSeries.pageviewsCompare
    }
    return null
}

const fallbackSeries: SeriesData = {
    label: 'Unknown',
    data: [1, 1, 1, 1, 1],
    days,
    labels,
}

export function lookupSeries(eventName: string, breakdownProperty?: string): SeriesData[] {
    const config = seriesByEvent[eventName]
    if (!config) {
        return [{ ...fallbackSeries, label: eventName }]
    }
    if (breakdownProperty && config.breakdowns?.[breakdownProperty]) {
        return config.breakdowns[breakdownProperty]
    }
    if (config.multi) {
        return config.multi
    }
    return [config.default]
}

// Canned actor lookups keyed by (event, breakdown_value, day). Lets the
// default ActorsQuery mock return different persons for different click
// contexts so tests can assert on displayed names instead of poking at the
// raw query body — if the wrong persons show up, we know the query was wrong.

export interface ActorFixture {
    email: string
}

/** Nested map: event → breakdown_value ('__none__' when no breakdown) → day → actors. */
const actorsByEventBreakdownDay: Record<string, Record<string, Record<string, ActorFixture[]>>> = {
    $pageview: {
        __none__: {
            '2024-06-10': [{ email: 'pageview-mon-a@example.com' }],
            '2024-06-11': [{ email: 'pageview-tue-a@example.com' }],
            '2024-06-12': [{ email: 'pageview-wed-a@example.com' }, { email: 'pageview-wed-b@example.com' }],
            '2024-06-13': [{ email: 'pageview-thu-a@example.com' }],
            '2024-06-14': [{ email: 'pageview-fri-a@example.com' }],
        },
    },
    Napped: {
        Spike: {
            '2024-06-12': [{ email: 'spike-fan@example.com' }],
        },
        Bramble: {
            '2024-06-12': [{ email: 'bramble-fan@example.com' }],
        },
        Thistle: {
            '2024-06-12': [{ email: 'thistle-fan@example.com' }],
        },
    },
}

export interface ActorsLookupQuery {
    event?: string
    breakdown?: string | number | null
    day?: string | number | null
}

export function lookupActors({ event, breakdown, day }: ActorsLookupQuery): ActorFixture[] {
    if (!event || !day) {
        return []
    }
    const breakdownKey = breakdown == null ? '__none__' : String(breakdown)
    return actorsByEventBreakdownDay[event]?.[breakdownKey]?.[String(day)] ?? []
}
