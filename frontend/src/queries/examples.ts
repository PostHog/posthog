// This file contains example queries, used in storybook and in the /query interface.
import {
    EventsNode,
    DataTableNode,
    LegacyQuery,
    Node,
    NodeKind,
    TrendsQuery,
    FunnelsQuery,
    RetentionQuery,
    ActionsNode,
    PathsQuery,
    StickinessQuery,
    LifecycleQuery,
} from '~/queries/schema'
import {
    ChartDisplayType,
    InsightType,
    PropertyFilterType,
    PropertyOperator,
    // PropertyMathType,
    FilterLogicalOperator,
    StepOrderValue,
    PropertyGroupFilter,
} from '~/types'
import { defaultDataTableStringColumns } from '~/queries/nodes/DataTable/defaults'
import { ShownAsValue } from '~/lib/constants'

const Events: EventsNode = {
    kind: NodeKind.EventsNode,
    properties: [
        { type: PropertyFilterType.Event, key: '$browser', operator: PropertyOperator.Exact, value: 'Chrome' },
    ],
    limit: 100,
}

const EventsTable: DataTableNode = {
    kind: NodeKind.DataTableNode,
    columns: defaultDataTableStringColumns,
    source: Events,
}

const LegacyTrendsQuery: LegacyQuery = {
    kind: NodeKind.LegacyQuery,
    filters: {
        insight: InsightType.TRENDS,
        date_from: '-7d',
        events: [{ id: '$pageview', math: 'avg_count_per_actor', name: '$pageview', type: 'events', order: 0 }],
        display: ChartDisplayType.ActionsLineGraph,
        interval: 'day',
    },
}

const properties: PropertyGroupFilter = {
    type: FilterLogicalOperator.And,
    values: [
        {
            type: FilterLogicalOperator.Or,
            values: [
                {
                    type: PropertyFilterType.Event,
                    key: '$current_url',
                    operator: PropertyOperator.Exact,
                    value: ['https://hedgebox.net/files/'],
                },
                {
                    type: PropertyFilterType.Event,
                    key: '$geoip_country_code',
                    operator: PropertyOperator.Exact,
                    value: ['US', 'AU'],
                },
            ],
        },
    ],
}

const filterTestAccounts = false
const series: (EventsNode | ActionsNode)[] = [
    {
        kind: NodeKind.EventsNode,
        name: '$pageview',
        custom_name: 'Views',
        event: '$pageview',
        properties: [
            {
                type: PropertyFilterType.Event,
                key: '$browser',
                operator: PropertyOperator.Exact,
                value: 'Chrome',
            },
            {
                type: PropertyFilterType.Cohort,
                key: 'id',
                value: 2,
            },
        ],
        limit: 100, // TODO - can't find a use for `limits` in insights/trends
    },
    // {
    //     kind: NodeKind.ActionsNode,
    //     id: 1,
    //     name: 'Interacted with file',
    //     custom_name: 'Interactions',
    //     properties: [
    //         {
    //             type: PropertyFilterType.Event,
    //             key: '$geoip_country_code',
    //             operator: PropertyOperator.Exact,
    //             value: ['US'],
    //         },
    //     ],
    //     math: PropertyMathType.Average,
    //     math_property: '$session_duration',
    // },
]

const InsightTrendsQuery: TrendsQuery = {
    kind: NodeKind.TrendsQuery,
    properties,
    filterTestAccounts,
    interval: 'day',
    dateRange: {
        date_from: '-7d',
    },
    series,
    trendsFilter: {
        display: ChartDisplayType.ActionsAreaGraph,
    },
    breakdown: {
        breakdown: '$geoip_country_code',
        breakdown_type: 'event',
    },
}

const InsightFunnelsQuery: FunnelsQuery = {
    kind: NodeKind.FunnelsQuery,
    properties,
    filterTestAccounts,
    interval: 'day',
    dateRange: {
        date_from: '-7d',
    },
    series,
    funnelsFilter: {
        funnel_order_type: StepOrderValue.ORDERED,
    },
    breakdown: {
        breakdown: '$geoip_country_code',
        breakdown_type: 'event',
    },
}

const InsightRetentionQuery: RetentionQuery = {
    kind: NodeKind.RetentionQuery,
    properties,
    filterTestAccounts,
    retentionFilter: {
        // TODO: this should be typed as (EventsNode | ActionsNode)[] without math and properties
        target_entity: { type: 'events', id: '$pageview', name: '$pageview' },
        returning_entity: { type: 'events', id: '$pageview', name: '$pageview' },
    },
}

const InsightPathsQuery: PathsQuery = {
    kind: NodeKind.PathsQuery,
    properties,
    filterTestAccounts,
    pathsFilter: {},
}

const InsightStickinessQuery: StickinessQuery = {
    kind: NodeKind.StickinessQuery,
    properties,
    filterTestAccounts,
    interval: 'day',
    dateRange: {
        date_from: '-7d',
    },
    series,
    stickinessFilter: {},
}

const InsightLifecycleQuery: LifecycleQuery = {
    kind: NodeKind.LifecycleQuery,
    properties,
    filterTestAccounts,
    dateRange: {
        date_from: '-7d',
    },
    series, // TODO: Visualization only supports one event or action
    lifecycleFilter: {
        shown_as: ShownAsValue.LIFECYCLE,
    },
}

export const examples: Record<string, Node> = {
    Events,
    EventsTable,
    LegacyTrendsQuery,
    InsightTrendsQuery,
    InsightFunnelsQuery,
    InsightRetentionQuery,
    InsightPathsQuery,
    InsightStickinessQuery,
    InsightLifecycleQuery,
}

export const stringifiedExamples: Record<string, string> = Object.fromEntries(
    Object.entries(examples).map(([key, node]) => [key, JSON.stringify(node)])
)
