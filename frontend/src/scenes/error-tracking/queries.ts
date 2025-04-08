import {
    DataTableNode,
    DateRange,
    ErrorTrackingQuery,
    EventsQuery,
    InsightVizNode,
    NodeKind,
} from '~/queries/schema/schema-general'
import {
    AnyPropertyFilter,
    BaseMathType,
    ChartDisplayType,
    EventPropertyFilter,
    PropertyFilterType,
    PropertyGroupFilter,
    PropertyOperator,
    UniversalFiltersGroup,
} from '~/types'

import { resolveDateRange, SEARCHABLE_EXCEPTION_PROPERTIES } from './utils'

export const errorTrackingQuery = ({
    orderBy,
    status,
    dateRange,
    assignee,
    filterTestAccounts,
    filterGroup,
    searchQuery,
    volumeResolution = 0,
    columns,
    orderDirection,
    limit = 50,
}: Pick<
    ErrorTrackingQuery,
    'orderBy' | 'status' | 'dateRange' | 'assignee' | 'filterTestAccounts' | 'limit' | 'searchQuery' | 'orderDirection'
> & {
    filterGroup: UniversalFiltersGroup
    columns: ('error' | 'volume' | 'occurrences' | 'sessions' | 'users' | 'assignee')[]
    volumeResolution?: number
}): DataTableNode => {
    return {
        kind: NodeKind.DataTableNode,
        source: {
            kind: NodeKind.ErrorTrackingQuery,
            orderBy,
            status,
            dateRange: resolveDateRange(dateRange).toDateRange(),
            assignee,
            volumeResolution,
            filterGroup: filterGroup as PropertyGroupFilter,
            filterTestAccounts: filterTestAccounts,
            searchQuery: searchQuery,
            limit: limit,
            orderDirection,
        },
        showActions: false,
        showTimings: false,
        columns: columns,
    }
}

export const errorTrackingIssueQuery = ({
    issueId,
    dateRange,
    volumeResolution,
}: {
    issueId: string
    dateRange: DateRange
    volumeResolution: number
}): ErrorTrackingQuery => {
    return {
        kind: NodeKind.ErrorTrackingQuery,
        issueId,
        dateRange: resolveDateRange(dateRange).toDateRange(),
        filterTestAccounts: false,
        volumeResolution,
    }
}

export const errorTrackingIssueEventsQuery = ({
    issueId,
    filterTestAccounts,
    filterGroup,
    searchQuery,
    dateRange,
}: {
    issueId: string | null
    filterTestAccounts: boolean
    filterGroup: UniversalFiltersGroup
    searchQuery: string
    dateRange: DateRange
}): DataTableNode | null => {
    if (!issueId) {
        return null
    }
    if (!dateRange.date_from) {
        throw new Error('date_from is required')
    }

    // const select = ['person', 'timestamp', 'recording_button(properties.$session_id)']
    // row expansion only works when you fetch the entire event with '*'
    const columns = ['*', 'person', 'timestamp', 'recording_button(properties.$session_id)']
    const group = filterGroup.values[0] as UniversalFiltersGroup
    const properties = [...group.values] as AnyPropertyFilter[]

    if (searchQuery) {
        properties.push(
            ...SEARCHABLE_EXCEPTION_PROPERTIES.map(
                (prop): EventPropertyFilter => ({
                    type: PropertyFilterType.Event,
                    operator: PropertyOperator.IContains,
                    key: prop,
                    value: searchQuery,
                })
            )
        )
    }

    const where = [`'${issueId}' == issue_id`]

    const eventsQuery: EventsQuery = {
        kind: NodeKind.EventsQuery,
        event: '$exception',
        select: columns,
        where,
        properties,
        filterTestAccounts: filterTestAccounts,
        after: dateRange.date_from,
        before: dateRange.date_to || undefined,
    }

    return {
        kind: NodeKind.DataTableNode,
        source: eventsQuery,
        showActions: false,
        showTimings: false,
        columns: columns,
        expandable: true,
        embedded: true,
    }
}

export const errorTrackingIssueBreakdownQuery = ({
    breakdownProperty,
    dateRange,
    filterTestAccounts,
    filterGroup,
}: {
    breakdownProperty: string
    dateRange: DateRange
    filterTestAccounts: boolean
    filterGroup: UniversalFiltersGroup
}): InsightVizNode => {
    return {
        kind: NodeKind.InsightVizNode,
        source: {
            kind: NodeKind.TrendsQuery,
            trendsFilter: {
                display: ChartDisplayType.ActionsBarValue,
            },
            breakdownFilter: {
                breakdown_type: 'event',
                breakdown: breakdownProperty,
                breakdown_limit: 10,
            },
            series: [
                {
                    kind: NodeKind.EventsNode,
                    event: '$exception',
                    math: BaseMathType.TotalCount,
                },
            ],
            dateRange: dateRange,
            properties: filterGroup.values as AnyPropertyFilter[],
            filterTestAccounts,
        },
    }
}
