import { UniversalFiltersGroup } from 'lib/components/UniversalFilters/UniversalFilters'
import { dayjs } from 'lib/dayjs'
import { range } from 'lib/utils'

import { DataTableNode, DateRange, ErrorTrackingOrder, EventsQuery, InsightVizNode, NodeKind } from '~/queries/schema'
import { AnyPropertyFilter, BaseMathType, ChartDisplayType } from '~/types'

export const errorTrackingQuery = ({
    order,
    dateRange,
    filterTestAccounts,
    filterGroup,
}: {
    order: ErrorTrackingOrder
    dateRange: DateRange
    filterTestAccounts: boolean
    filterGroup: UniversalFiltersGroup
}): DataTableNode => {
    const period = 24
    const unit = 'hour'
    const labels = generateFormattedDateLabels(period, unit)

    return {
        kind: NodeKind.DataTableNode,
        source: {
            kind: NodeKind.EventsQuery,
            select: [
                'any(properties) -- context.columns.error',
                'properties.$exception_type',
                `sparkline(reverse(arrayMap(x -> countEqual(groupArray(dateDiff('${unit}', now() - INTERVAL ${period} ${unit}, timestamp)), x), range(${period}))), [${labels}]) -- context.columns.volume`,
                'count() as unique_occurrences -- Occurrences',
                'count(distinct $session_id) as unique_sessions -- Sessions',
                'count(distinct distinct_id) as unique_users -- Users',
                'max(timestamp) as last_seen',
                'min(timestamp) as first_seen',
            ],
            orderBy: [order],
            ...defaultProperties({ dateRange, filterTestAccounts, filterGroup }),
        },
        hiddenColumns: [
            'properties.$exception_type',
            'first_value(properties)',
            'max(timestamp) as last_seen',
            'min(timestamp) as first_seen',
        ],
        showActions: false,
        showTimings: false,
    }
}

const generateFormattedDateLabels = (period: number, unit: 'hour'): string => {
    const now = dayjs().startOf(unit)
    const formattedDates = range(period).map((idx) => now.subtract(period - idx, unit))
    const stringifiedDates = formattedDates.map((d) => `'${d.format('D MMM, YYYY HH:mm')} (UTC)'`)
    return stringifiedDates.join(',')
}

export const errorTrackingGroupQuery = ({
    group,
    dateRange,
    filterTestAccounts,
    filterGroup,
}: {
    group: string
    dateRange: DateRange
    filterTestAccounts: boolean
    filterGroup: UniversalFiltersGroup
}): EventsQuery => {
    return {
        kind: NodeKind.EventsQuery,
        select: ['uuid', 'properties', 'timestamp', 'person'],
        where: [`properties.$exception_type = '${group}'`],
        ...defaultProperties({ dateRange, filterTestAccounts, filterGroup }),
    }
}

export const errorTrackingGroupBreakdownQuery = ({
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
                    event: '$pageview',
                    math: BaseMathType.TotalCount,
                    name: 'This is the series name',
                    custom_name: 'Boomer',
                },
            ],
            dateRange: dateRange,
            properties: filterGroup.values as AnyPropertyFilter[],
            filterTestAccounts,
        },
    }
}

const defaultProperties = ({
    dateRange,
    filterTestAccounts,
    filterGroup,
}: {
    dateRange: DateRange
    filterTestAccounts: boolean
    filterGroup: UniversalFiltersGroup
}): Pick<EventsQuery, 'event' | 'after' | 'before' | 'filterTestAccounts' | 'properties'> => {
    const properties = filterGroup.values as AnyPropertyFilter[]

    return {
        event: '$pageview',
        after: dateRange.date_from || undefined,
        before: dateRange.date_to || undefined,
        filterTestAccounts,
        properties,
    }
}
