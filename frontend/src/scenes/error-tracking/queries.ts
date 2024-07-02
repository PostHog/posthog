import { UniversalFiltersGroup } from 'lib/components/UniversalFilters/UniversalFilters'
import { dayjs } from 'lib/dayjs'
import { range } from 'lib/utils'

import { DataTableNode, DateRange, ErrorTrackingOrder, EventsQuery, InsightVizNode, NodeKind } from '~/queries/schema'
import { AnyPropertyFilter, BaseMathType, ChartDisplayType } from '~/types'

import { ErrorTrackingSparklineConfig } from './errorTrackingLogic'

export const errorTrackingQuery = ({
    order,
    dateRange,
    filterTestAccounts,
    sparklineSelection,
    filterGroup,
}: {
    order: ErrorTrackingOrder
    dateRange: DateRange
    filterTestAccounts: boolean
    filterGroup: UniversalFiltersGroup
    sparklineSelection: ErrorTrackingSparklineConfig
}): DataTableNode => {
    const { period, displayInterval, displayGap, offset } = sparklineSelection

    const labels = generateFormattedDateLabels({ period, displayInterval, displayGap, offset })

    return {
        kind: NodeKind.DataTableNode,
        source: {
            kind: NodeKind.EventsQuery,
            select: [
                'any(properties) as "context.columns.error"',
                'properties.$exception_type',
                `<Sparkline data={reverse(arrayMap(x -> countEqual(groupArray(dateDiff('${displayInterval}', now() - INTERVAL ${period} ${displayInterval}, timestamp)), x), range(${
                    period * displayGap
                })))} labels={[${labels}]} /> as "context.columns.volume"`,
                'count() as occurrences',
                'count(distinct $session_id) as sessions',
                'count(distinct distinct_id) as users',
                'max(timestamp) as last_seen',
                'min(timestamp) as first_seen',
            ],
            orderBy: [order],
            ...defaultProperties({ dateRange, filterTestAccounts, filterGroup }),
        },
        hiddenColumns: ['$exception_type', 'last_seen', 'first_seen'],
        showActions: false,
        showTimings: false,
        columns: [
            'context.columns.error',
            '$exception_type',
            'context.columns.volume',
            'occurrences',
            'sessions',
            'users',
            'last_seen',
            'first_seen',
        ],
    }
}

const generateFormattedDateLabels = ({
    period,
    displayInterval,
    displayGap,
    offset,
}: ErrorTrackingSparklineConfig): string => {
    const now = dayjs()
        .subtract(offset?.value ?? 0, offset?.unit)
        .startOf(displayInterval)
    const formattedDates = range(period * displayGap).map((idx) =>
        now.subtract(period - idx * displayGap, displayInterval)
    )
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
