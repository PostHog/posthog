import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { DataTableNode, NodeKind, PersonsNode } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator } from '~/types'

const AllDefaults: DataTableNode = {
    kind: NodeKind.DataTableNode,
    source: { kind: NodeKind.EventsQuery, select: defaultDataTableColumns(NodeKind.EventsQuery) },
}

const Minimalist: DataTableNode = {
    kind: NodeKind.DataTableNode,
    source: { kind: NodeKind.EventsQuery, select: defaultDataTableColumns(NodeKind.EventsQuery) },
    showActions: false,
    expandable: false,
}

const ManyColumns: DataTableNode = {
    kind: NodeKind.DataTableNode,
    source: { kind: NodeKind.EventsQuery, select: defaultDataTableColumns(NodeKind.EventsQuery) },
    columns: [
        'id',
        'event',
        'timestamp',
        'url',
        'person',
        'properties.$current_url',
        'properties.$browser',
        'properties.$browser_version',
        'properties.$lib',
        'person.properties.email',
    ],
}

const ShowFilters: DataTableNode = {
    kind: NodeKind.DataTableNode,
    source: {
        kind: NodeKind.EventsQuery,
        select: defaultDataTableColumns(NodeKind.EventsQuery),
        properties: [
            {
                key: '$browser',
                value: ['Chrome'],
                operator: PropertyOperator.Exact,
                type: PropertyFilterType.Event,
            },
        ],
        event: '',
        limit: 100,
    },
    columns: ['event', 'person', 'properties.$lib', 'person.properties.email'],
    showEventFilter: true,
    showPropertyFilter: true,
}

const ShowTools: DataTableNode = {
    kind: NodeKind.DataTableNode,
    source: { kind: NodeKind.EventsQuery, select: defaultDataTableColumns(NodeKind.EventsQuery) },
    columns: ['event', 'person', 'properties.$lib', 'person.properties.email'],
    showExport: true,
    showReload: true,
    showColumnConfigurator: true,
}

const ShowAllTheThings: DataTableNode = {
    kind: NodeKind.DataTableNode,
    source: {
        kind: NodeKind.EventsQuery,
        select: defaultDataTableColumns(NodeKind.EventsQuery),
        properties: [
            {
                key: '$browser',
                value: ['Chrome'],
                operator: PropertyOperator.Exact,
                type: PropertyFilterType.Event,
            },
        ],
        event: '',
        limit: 100,
    },
    columns: ['event', 'person', 'properties.$lib', 'person.properties.email'],
    showExport: true,
    showReload: true,
    showColumnConfigurator: true,
    showEventFilter: true,
    showPropertyFilter: true,
}

const Persons: PersonsNode = {
    kind: NodeKind.PersonsNode,
}

const PersonsTable: DataTableNode = {
    kind: NodeKind.DataTableNode,
    source: Persons,
    columns: defaultDataTableColumns(NodeKind.PersonsNode),
    showSearch: true,
    showPropertyFilter: true,
    showExport: true,
    showReload: true,
}

const MarketingAnalyticsTablePinnedColumns: DataTableNode = {
    kind: NodeKind.DataTableNode,
    source: {
        kind: NodeKind.MarketingAnalyticsTableQuery,
        select: [
            'campaign',
            'source',
            'cost',
            'impressions',
            'clicks',
            'extra table 1',
            'extra table 2',
            'extra table 3',
            'extra table 4',
            'extra table 5',
            'extra table 6',
            'extra table 7',
            'extra table 8',
            'extra table 9',
            'extra table 10',
        ],
        properties: [],
        limit: 100,
    },
    pinnedColumns: ['source', 'impressions'],
}

export const examples = {
    AllDefaults,
    Minimalist,
    ManyColumns,
    ShowFilters,
    ShowTools,
    ShowAllTheThings,
    Persons,
    PersonsTable,
    MarketingAnalyticsTablePinnedColumns,
}
