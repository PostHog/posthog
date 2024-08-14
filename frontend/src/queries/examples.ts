// This file contains example queries, used in storybook and in the /query interface.
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import {
    ActionsNode,
    DataTableNode,
    DataVisualizationNode,
    EventsNode,
    EventsQuery,
    FunnelsQuery,
    HogQLQuery,
    HogQuery,
    InsightVizNode,
    LifecycleQuery,
    Node,
    NodeKind,
    PathsQuery,
    PersonsNode,
    RetentionQuery,
    StickinessQuery,
    TrendsQuery,
} from '~/queries/schema'
import {
    ChartDisplayType,
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyGroupFilter,
    PropertyOperator,
    StepOrderValue,
} from '~/types'

const Events: EventsQuery = {
    kind: NodeKind.EventsQuery,
    select: defaultDataTableColumns(NodeKind.EventsQuery),
    properties: [
        { type: PropertyFilterType.Event, key: '$browser', operator: PropertyOperator.Exact, value: 'Chrome' },
    ],
    after: '-24h',
    limit: 100,
}

const EventsTable: DataTableNode = {
    kind: NodeKind.DataTableNode,
    source: Events,
}
const EventsTableFull: DataTableNode = {
    kind: NodeKind.DataTableNode,
    full: true,
    source: Events,
}

const TotalEvents: EventsQuery = {
    kind: NodeKind.EventsQuery,
    select: ['count()'],
}

export const TotalEventsTable: DataTableNode = {
    kind: NodeKind.DataTableNode,
    full: true,
    source: TotalEvents,
}

const PropertyFormulas: EventsQuery = {
    kind: NodeKind.EventsQuery,
    select: [
        '1 + 2 + 3',
        'event',
        'person.created_at',
        "concat(properties['$browser'], ' 💚 ', properties['$geoip_city_name']) -- Browser 💚 City",
        "'random string'",
    ],
    limit: 100,
}

const PropertyFormulasTable: DataTableNode = {
    kind: NodeKind.DataTableNode,
    full: true,
    source: PropertyFormulas,
}

const EventAggregations: DataTableNode = {
    kind: NodeKind.DataTableNode,
    full: true,
    source: {
        kind: NodeKind.EventsQuery,
        select: [
            "concat(properties['$geoip_city_name'], ' ', 'Rocks') -- City",
            'event',
            'count() + 100000 -- Inflamed total',
            '1 + 2',
        ],
        orderBy: ['-count()'],
    },
}

const Persons: PersonsNode = {
    kind: NodeKind.PersonsNode,
    properties: [
        { type: PropertyFilterType.Person, key: '$browser', operator: PropertyOperator.Exact, value: 'Chrome' },
    ],
}

const PersonsTable: DataTableNode = {
    kind: NodeKind.DataTableNode,
    columns: defaultDataTableColumns(NodeKind.PersonsNode),
    source: Persons,
}

const PersonsTableFull: DataTableNode = {
    kind: NodeKind.DataTableNode,
    full: true,
    columns: defaultDataTableColumns(NodeKind.PersonsNode),
    source: Persons,
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
    breakdownFilter: {
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
        funnelOrderType: StepOrderValue.ORDERED,
    },
    breakdownFilter: {
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
        targetEntity: { type: 'events', id: '$pageview', name: '$pageview' },
        returningEntity: { type: 'events', id: '$pageview', name: '$pageview' },
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
}

const HogQLRaw: HogQLQuery = {
    kind: NodeKind.HogQLQuery,
    query: `   select event,
          person.properties.email,
          properties.$browser,
          count()
     from events
    where {filters} -- replaced with global date and property filters
      and person.properties.email is not null
 group by event,
          properties.$browser,
          person.properties.email
 order by count() desc
    limit 100`,
    filters: {
        dateRange: {
            date_from: '-24h',
        },
    },
}

const HogQLForDataVisualization: HogQLQuery = {
    kind: NodeKind.HogQLQuery,
    query: `select toDate(timestamp) as timestamp, count()
from events
where {filters} and timestamp <= now()
group by timestamp
order by timestamp asc
limit 100`,
    explain: true,
    filters: {
        dateRange: {
            date_from: '-7d',
        },
    },
}

const HogQLForDataWarehouse: HogQLQuery = {
    kind: NodeKind.HogQLQuery,
    query: `select toDate(timestamp) as timestamp, count()
from events
group by timestamp
limit 100`,
    explain: true,
}

const DataWarehouse: DataVisualizationNode = {
    kind: NodeKind.DataVisualizationNode,
    source: HogQLForDataWarehouse,
}

const HogQLTable: DataTableNode = {
    kind: NodeKind.DataTableNode,
    full: true,
    source: HogQLRaw,
}

const DataVisualization: DataVisualizationNode = {
    kind: NodeKind.DataVisualizationNode,
    source: HogQLForDataVisualization,
}

const Hog: HogQuery = {
    kind: NodeKind.HogQuery,
    code: 'return 1 + 2;',
}

const Hoggonacci: HogQuery = {
    kind: NodeKind.HogQuery,
    code: `fn fibonacci(number) {
    if (number < 2) {
        return number;
    } else {
        return fibonacci(number - 1) + fibonacci(number - 2);
    }
}
return fibonacci(16);`,
}
/* a subset of examples including only those we can show all users and that don't use HogQL */
export const queryExamples: Record<string, Node> = {
    Events,
    EventsTable,
    EventsTableFull,
    TotalEventsTable,
    PropertyFormulasTable,
    EventAggregations,
    Persons,
    PersonsTable,
    PersonsTableFull,
    InsightTrendsQuery,
    InsightTrends: { kind: NodeKind.InsightVizNode, source: InsightTrendsQuery } as InsightVizNode<TrendsQuery>,
    InsightFunnelsQuery,
    InsightFunnels: { kind: NodeKind.InsightVizNode, source: InsightFunnelsQuery } as InsightVizNode<FunnelsQuery>,
    InsightRetentionQuery,
    InsightRetention: {
        kind: NodeKind.InsightVizNode,
        source: InsightRetentionQuery,
    } as InsightVizNode<RetentionQuery>,
    InsightPathsQuery,
    InsightPaths: { kind: NodeKind.InsightVizNode, source: InsightPathsQuery } as InsightVizNode<PathsQuery>,
    InsightStickinessQuery,
    InsightStickiness: {
        kind: NodeKind.InsightVizNode,
        source: InsightStickinessQuery,
    } as InsightVizNode<StickinessQuery>,
    InsightLifecycleQuery,
    InsightLifecycle: {
        kind: NodeKind.InsightVizNode,
        source: InsightLifecycleQuery,
    } as InsightVizNode<LifecycleQuery>,
}

export const stringifiedQueryExamples: Record<string, string> = Object.fromEntries(
    Object.entries(queryExamples).map(([key, node]) => [key, JSON.stringify(node)])
)

export const examples: Record<string, Node> = {
    ...queryExamples,
    HogQLRaw,
    HogQLTable,
    DataVisualization,
    Hog,
    Hoggonacci,
    DataWarehouse,
}

export const stringifiedExamples: Record<string, string> = Object.fromEntries(
    Object.entries(examples).map(([key, node]) => [key, JSON.stringify(node)])
)
