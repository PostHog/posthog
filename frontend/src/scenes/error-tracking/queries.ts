import { ErrorTrackingSparklineConfig } from 'lib/components/Errors/types'

import {
    DataTableNode,
    DateRange,
    ErrorTrackingIssue,
    ErrorTrackingQuery,
    EventsQuery,
    InsightVizNode,
    NodeKind,
} from '~/queries/schema'
import { AnyPropertyFilter, BaseMathType, ChartDisplayType, PropertyGroupFilter, UniversalFiltersGroup } from '~/types'

export const errorTrackingQuery = ({
    orderBy,
    dateRange,
    assignee,
    filterTestAccounts,
    filterGroup,
    searchQuery,
    customVolume,
    columns,
    limit = 50,
}: Pick<ErrorTrackingQuery, 'orderBy' | 'dateRange' | 'assignee' | 'filterTestAccounts' | 'limit' | 'searchQuery'> & {
    filterGroup: UniversalFiltersGroup
    customVolume?: ErrorTrackingSparklineConfig | null
    columns: ('error' | 'occurrences' | 'sessions' | 'users' | 'assignee')[]
}): DataTableNode => {
    return {
        kind: NodeKind.DataTableNode,
        source: {
            kind: NodeKind.ErrorTrackingQuery,
            orderBy,
            dateRange,
            assignee,
            customVolume,
            filterGroup: filterGroup as PropertyGroupFilter,
            filterTestAccounts: filterTestAccounts,
            searchQuery: searchQuery,
            limit: limit,
        },
        showActions: false,
        showTimings: false,
        columns: columns,
    }
}

export const errorTrackingIssueQuery = ({
    issueId,
    dateRange,
    filterTestAccounts,
    filterGroup,
}: {
    issueId: string
    dateRange: DateRange
    filterTestAccounts: boolean
    filterGroup: UniversalFiltersGroup
}): ErrorTrackingQuery => {
    return {
        kind: NodeKind.ErrorTrackingQuery,
        issueId: issueId,
        dateRange: dateRange,
        filterGroup: filterGroup as PropertyGroupFilter,
        filterTestAccounts: filterTestAccounts,
    }
}

export const errorTrackingIssueEventsQuery = ({
    issueId,
    dateRange,
    filterTestAccounts,
    filterGroup,
}: {
    issueId: ErrorTrackingIssue['id']
    dateRange: DateRange
    filterTestAccounts: boolean
    filterGroup: UniversalFiltersGroup
}): DataTableNode => {
    // const select = ['person', 'timestamp', 'recording_button(properties.$session_id)']
    // row expansion only works when you fetch the entire event with '*'
    const columns = ['*', 'person', 'timestamp', 'recording_button(properties.$session_id)']

    const group = filterGroup.values[0] as UniversalFiltersGroup
    const properties = group.values as AnyPropertyFilter[]

    // TODO: fix this where clause. It does not take into account the events
    // associated with issues that have been merged into this primary issue
    const where = [`'${issueId}' == properties.$exception_issue_id`]

    const eventsQuery: EventsQuery = {
        kind: NodeKind.EventsQuery,
        event: '$exception',
        select: columns,
        where,
        properties,
        filterTestAccounts: filterTestAccounts,
    }

    if (dateRange.date_from) {
        eventsQuery.after = dateRange.date_from
    }
    if (dateRange.date_to) {
        eventsQuery.before = dateRange.date_to
    }

    return {
        kind: NodeKind.DataTableNode,
        source: eventsQuery,
        showActions: false,
        showTimings: false,
        columns: columns,
        expandable: true,
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
