// This file contains example queries, used in storybook and in the /query interface.
import { EventsNode, DataTableNode, LegacyQuery, Node, NodeKind, TrendsQuery, FunnelsQuery } from '~/queries/schema'
import {
    ChartDisplayType,
    InsightType,
    PropertyFilterType,
    PropertyOperator,
    PropertyMathType,
    FilterLogicalOperator,
} from '~/types'
import { defaultDataTableStringColumns } from '~/queries/nodes/DataTable/DataTable'

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

const InsightTrendsQuery: TrendsQuery = {
    kind: NodeKind.TrendsQuery,
    interval: 'day',
    dateRange: {
        date_from: '-7d',
    },
    series: [
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
        {
            kind: NodeKind.ActionsNode,
            id: 1,
            name: 'Interacted with file',
            custom_name: 'Interactions',
            properties: [
                {
                    type: PropertyFilterType.Event,
                    key: '$geoip_country_code',
                    operator: PropertyOperator.Exact,
                    value: ['US'],
                },
            ],
            math: PropertyMathType.Average,
            math_property: '$session_duration',
        },
    ],
    filterTestAccounts: false,
    properties: {
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
    },
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
    interval: 'day',
    dateRange: {
        date_from: '-7d',
    },
    series: [
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
        {
            kind: NodeKind.ActionsNode,
            id: 1,
            name: 'Interacted with file',
            custom_name: 'Interactions',
            properties: [
                {
                    type: PropertyFilterType.Event,
                    key: '$geoip_country_code',
                    operator: PropertyOperator.Exact,
                    value: ['US'],
                },
            ],
            math: PropertyMathType.Average,
            math_property: '$session_duration',
        },
    ],
    filterTestAccounts: false,
    properties: {
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
    },
    // trendsFilter: {
    //     display: ChartDisplayType.ActionsAreaGraph,
    // },
    breakdown: {
        breakdown: '$geoip_country_code',
        breakdown_type: 'event',
    },
}

export const examples: Record<string, Node> = {
    Events,
    EventsTable,
    LegacyTrendsQuery,
    InsightTrendsQuery,
    InsightFunnelsQuery,
}

export const stringifiedExamples: Record<string, string> = Object.fromEntries(
    Object.entries(examples).map(([key, node]) => [key, JSON.stringify(node)])
)
