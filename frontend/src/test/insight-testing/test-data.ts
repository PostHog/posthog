import { AnnotationScope, EventDefinition, PropertyDefinition, PropertyType, RawAnnotationType } from '~/types'

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

/** Build a RawAnnotationType for use in setupInsightMocks({ annotations }).
 *  Generates a random id so identifiers don't carry deterministic state across tests. */
export function buildAnnotation(overrides: Partial<RawAnnotationType> = {}): RawAnnotationType {
    return {
        id: Math.floor(Math.random() * 1_000_000),
        scope: AnnotationScope.Project,
        content: 'Hedgehog spotted',
        date_marker: '2024-06-12T12:00:00Z',
        created_at: '2024-06-10T00:00:00Z',
        updated_at: '2024-06-10T00:00:00Z',
        ...overrides,
    }
}

export function lookupActors({ event, breakdown, day }: ActorsLookupQuery): ActorFixture[] {
    if (!event || !day) {
        return []
    }
    const breakdownKey = breakdown == null ? '__none__' : String(breakdown)
    return actorsByEventBreakdownDay[event]?.[breakdownKey]?.[String(day)] ?? []
}

// Funnel trends-viz response shape: `data` holds the conversion percentage over time.
export interface FunnelStepData {
    count: number
    data: number[]
    days: string[]
    labels: string[]
    name?: string
    breakdown_value?: string | number
    // The funnels runner tags compare rows with `compare_label` (it doesn't set `compare`).
    compare_label?: 'current' | 'previous'
}

export const funnelTrendsSteps = {
    default: {
        count: 50,
        data: [10, 25, 40, 60, 35],
        days,
        labels,
        name: '$pageview → Napped',
    } satisfies FunnelStepData,
    byBreakdown: {
        hedgehog: [
            {
                count: 30,
                data: [20, 35, 50, 70, 45],
                days,
                labels,
                name: '$pageview → Napped',
                breakdown_value: 'Spike',
            },
            {
                count: 20,
                data: [5, 15, 30, 50, 25],
                days,
                labels,
                name: '$pageview → Napped',
                breakdown_value: 'Bramble',
            },
        ] satisfies FunnelStepData[],
        // Query order (Safari, Chrome, Firefox), alphabetical order, and value-at-index-2 order
        // (Firefox 60, Safari 40, Chrome 20) all differ, so a tooltip sorted by descending value
        // can't accidentally match the input order.
        browser: [
            {
                count: 40,
                data: [30, 35, 40, 45, 38],
                days,
                labels,
                name: '$pageview → Napped',
                breakdown_value: 'Safari',
            },
            {
                count: 20,
                data: [10, 15, 20, 25, 18],
                days,
                labels,
                name: '$pageview → Napped',
                breakdown_value: 'Chrome',
            },
            {
                count: 60,
                data: [50, 55, 60, 65, 58],
                days,
                labels,
                name: '$pageview → Napped',
                breakdown_value: 'Firefox',
            },
        ] satisfies FunnelStepData[],
    } as Record<string, FunnelStepData[]>,
    // Compare-to-previous + breakdown: current and previous rows per breakdown value, each
    // tagged with `compare_label` so the tooltip can split them into their own rows.
    compareByBreakdown: {
        hedgehog: [
            {
                count: 30,
                data: [20, 35, 50, 70, 45],
                days,
                labels,
                name: '$pageview → Napped',
                breakdown_value: 'Spike',
                compare_label: 'current',
            },
            {
                count: 28,
                data: [18, 30, 45, 65, 40],
                days,
                labels,
                name: '$pageview → Napped',
                breakdown_value: 'Spike',
                compare_label: 'previous',
            },
            {
                count: 20,
                data: [5, 15, 30, 50, 25],
                days,
                labels,
                name: '$pageview → Napped',
                breakdown_value: 'Bramble',
                compare_label: 'current',
            },
            {
                count: 18,
                data: [3, 10, 25, 45, 20],
                days,
                labels,
                name: '$pageview → Napped',
                breakdown_value: 'Bramble',
                compare_label: 'previous',
            },
        ] satisfies FunnelStepData[],
    } as Record<string, FunnelStepData[]>,
}

// Steps-viz funnel response shape: a flat FunnelStep[] (or FunnelStep[][] with a breakdown),
// one entry per step with the absolute converted count.
export interface FunnelStepFixture {
    action_id: string
    name: string
    custom_name: string | null
    order: number
    count: number
    type: 'events'
    average_conversion_time: number | null
    median_conversion_time: number | null
    breakdown?: string[]
    breakdown_value?: string[]
}

function buildFunnelStep(
    name: string,
    order: number,
    count: number,
    breakdownValue?: string,
    conversionTime?: number
): FunnelStepFixture {
    return {
        action_id: name,
        name,
        custom_name: null,
        order,
        count,
        type: 'events',
        average_conversion_time: conversionTime ?? null,
        median_conversion_time: conversionTime ?? null,
        ...(breakdownValue ? { breakdown: [breakdownValue], breakdown_value: [breakdownValue] } : {}),
    }
}

export const funnelSteps = {
    // 100 hedgehogs viewed → 60 napped → 30 snored.
    default: [
        buildFunnelStep('$pageview', 0, 100),
        buildFunnelStep('Napped', 1, 60),
        buildFunnelStep('Snored', 2, 30),
    ] satisfies FunnelStepFixture[],
    byBreakdown: {
        hedgehog: [
            [
                buildFunnelStep('$pageview', 0, 70, 'Spike'),
                buildFunnelStep('Napped', 1, 42, 'Spike'),
                buildFunnelStep('Snored', 2, 21, 'Spike'),
            ],
            [
                buildFunnelStep('$pageview', 0, 30, 'Bramble'),
                buildFunnelStep('Napped', 1, 18, 'Bramble'),
                buildFunnelStep('Snored', 2, 9, 'Bramble'),
            ],
        ] satisfies FunnelStepFixture[][],
    } as Record<string, FunnelStepFixture[][]>,
}

// Time-to-convert funnel response shape: histogram bins of [seconds, converted count]
// plus the overall average. Counts sum to 20 → bar labels 20% / 50% / 20% / 10%.
export interface FunnelTimeToConvertFixture {
    bins: [number, number][]
    average_conversion_time: number
}

export const funnelTimeToConvertBins = {
    bins: [
        [0, 4],
        [120, 10],
        [240, 4],
        [360, 2],
    ],
    average_conversion_time: 138,
} satisfies FunnelTimeToConvertFixture

// Retention response shape: one row per cohort with the cohort start `date` and the
// absolute retained `count` per interval. The frontend derives percentages from
// interval 0: Jun 10 → 100/60/30%, Jun 11 → 100/40/10%.
export interface RetentionResultFixture {
    date: string
    label: string
    values: { count: number }[]
    breakdown_value?: string | number | null
}

export const retentionResults: RetentionResultFixture[] = [
    {
        date: '2024-06-10T00:00:00Z',
        label: 'Day 0',
        values: [{ count: 100 }, { count: 60 }, { count: 30 }],
    },
    {
        date: '2024-06-11T00:00:00Z',
        label: 'Day 1',
        values: [{ count: 50 }, { count: 20 }, { count: 5 }],
    },
]

// Keyed by breakdown value (or '__none__'), then by calendar date.
const funnelActorsByBreakdownDay: Record<string, Record<string, ActorFixture[]>> = {
    __none__: {
        '2024-06-12': [{ email: 'funnel-wed-a@example.com' }, { email: 'funnel-wed-b@example.com' }],
        '2024-06-13': [{ email: 'funnel-thu-a@example.com' }],
    },
    Spike: {
        '2024-06-12': [{ email: 'funnel-spike@example.com' }],
    },
    Bramble: {
        '2024-06-12': [{ email: 'funnel-bramble@example.com' }],
    },
}

export interface FunnelActorsLookupQuery {
    day?: string | null
    breakdown?: string | number | null
}

export function lookupFunnelActors({ day, breakdown }: FunnelActorsLookupQuery): ActorFixture[] {
    if (!day) {
        return []
    }
    const breakdownKey = breakdown == null ? '__none__' : String(breakdown)
    return funnelActorsByBreakdownDay[breakdownKey]?.[day] ?? []
}
