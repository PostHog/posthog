import {
    DataTableNode,
    DateRange,
    ErrorTrackingIssue,
    ErrorTrackingQuery,
    EventsQuery,
    InsightVizNode,
    NodeKind,
} from '~/queries/schema/schema-general'
import { AnyPropertyFilter, BaseMathType, ChartDisplayType, PropertyGroupFilter, UniversalFiltersGroup } from '~/types'

export const errorTrackingQuery = ({
    orderBy,
    status,
    dateRange,
    assignee,
    filterTestAccounts,
    filterGroup,
    searchQuery,
    volumeResolution,
    columns,
    orderDirection,
    limit = 50,
}: Pick<
    ErrorTrackingQuery,
    | 'orderBy'
    | 'status'
    | 'dateRange'
    | 'assignee'
    | 'filterTestAccounts'
    | 'limit'
    | 'searchQuery'
    | 'orderDirection'
    | 'volumeResolution'
> & {
    filterGroup: UniversalFiltersGroup
    columns: ('error' | 'volume' | 'occurrences' | 'sessions' | 'users' | 'assignee')[]
}): DataTableNode => {
    return {
        kind: NodeKind.DataTableNode,
        source: {
            kind: NodeKind.ErrorTrackingQuery,
            orderBy,
            status,
            dateRange,
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
        dateRange,
        filterTestAccounts: false,
        volumeResolution,
    }
}

export const errorTrackingIssueEventsQuery = ({
    issue,
    filterTestAccounts,
    filterGroup,
    dateRange,
}: {
    issue: ErrorTrackingIssue | null
    filterTestAccounts: boolean
    filterGroup: UniversalFiltersGroup
    dateRange: DateRange
}): DataTableNode | null => {
    if (!issue) {
        return null
    }

    // const select = ['person', 'timestamp', 'recording_button(properties.$session_id)']
    // row expansion only works when you fetch the entire event with '*'
    const columns = ['*', 'person', 'timestamp', 'recording_button(properties.$session_id)']

    const group = filterGroup.values[0] as UniversalFiltersGroup
    const properties = group.values as AnyPropertyFilter[]
    const where = [`'${issue.id}' == issue_id`]

    const eventsQuery: EventsQuery = {
        kind: NodeKind.EventsQuery,
        event: '$exception',
        select: columns,
        where,
        properties,
        filterTestAccounts: filterTestAccounts,
        after: dateRange.date_from || issue.first_seen,
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
