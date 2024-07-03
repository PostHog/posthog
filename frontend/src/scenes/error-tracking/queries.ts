import { UniversalFiltersGroup } from 'lib/components/UniversalFilters/UniversalFilters'
import { dayjs } from 'lib/dayjs'
import { range } from 'lib/utils'

import { DataTableNode, DateRange, ErrorTrackingOrder, EventsQuery, InsightVizNode, NodeKind } from '~/queries/schema'
import { AnyPropertyFilter, BaseMathType, ChartDisplayType } from '~/types'

export type ErrorTrackingSparklineConfig = {
    value: number
    displayAs: 'minute' | 'hour' | 'day'
    gap: number
    offsetHours?: number
}

export const SPARKLINE_CONFIGURATIONS: Record<string, ErrorTrackingSparklineConfig> = {
    '1h': { value: 60, displayAs: 'minute', gap: 1 },
    '24h': { value: 24, displayAs: 'hour', gap: 1 },
    '7d': { value: 168, displayAs: 'hour', gap: 8 }, // 7d * 24h = 168h
    '14d': { value: 336, displayAs: 'hour', gap: 12 }, // 14d * 24h = 336h
    '90d': { value: 90, displayAs: 'day', gap: 5 },
    '180d': { value: 180, displayAs: 'day', gap: 10 },
}

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
    const { value, displayAs, gap, offsetHours } = sparklineSelection

    // const numInPeriod = displayAs === 'hour' ? 24 : 60
    // const unitsInPeriod = value * numInPeriod

    const labels = generateFormattedDateLabels({ value, displayAs, gap, offsetHours })

    const sparklineData = `reverse(arrayMap(x -> countEqual(groupArray(dateDiff('${displayAs}', toStartOfInterval(timestamp, INTERVAL ${gap} ${displayAs}), toStartOfInterval(now(), INTERVAL ${gap} ${displayAs}))), x), range(0, ${value}, ${gap})))`

    return {
        kind: NodeKind.DataTableNode,
        source: {
            kind: NodeKind.EventsQuery,
            select: [
                'any(properties) as "context.columns.error"',
                'properties.$exception_type',
                `<Sparkline data={${sparklineData}} labels={[${labels.join(',')}]} /> as "context.columns.volume"`,
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

export const generateFormattedDateLabels = ({
    value,
    displayAs,
    gap,
    offsetHours,
}: ErrorTrackingSparklineConfig): string[] => {
    const now = dayjs()
        .subtract(offsetHours ?? 0, 'hour')
        .startOf(displayAs)
    // const formattedDates = range(period * displayGap).map((idx) =>
    //     now.subtract(period - idx * displayGap, displayInterval)
    // )
    const formattedDates = range(value / gap).map((idx) => now.subtract(value - (idx + 1) * gap, displayAs))
    return formattedDates.map((d) => `'${d.format('D MMM, YYYY HH:mm')} (UTC)'`)
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

// -- 14 * 24 = 336
// -- with cte_timestamps as
// -- (
// --     SELECT
// --         subtractHours(now(), number) as timestamp
// --     FROM numbers(350)
// -- )
// -- select
// --     reverse(arrayMap(x -> countEqual(groupArray(dateDiff('hour', toStartOfInterval(timestamp, INTERVAL 12 HOUR), toStartOfInterval(now(), INTERVAL 12 HOUR))), x), range(0, 336, 12)))
// -- from cte_timestamps timestamp

// -- with cte_timestamps as
// -- (
// --     SELECT
// --         subtractMinutes(now(), number) as timestamp
// --     FROM numbers(80)
// -- )
// -- select
// --     reverse(arrayMap(x -> countEqual(groupArray(dateDiff('minute', toStartOfInterval(timestamp, INTERVAL 3 MINUTE), toStartOfInterval(now(), INTERVAL 3 MINUTE))), x), range(0, 60, 3)))
// -- from cte_timestamps timestamp

// with cte_timestamps as
// (
//     SELECT
//         subtractMinutes(now(), number) as timestamp
//     FROM numbers(80)
// )
// select
//     reverse(arrayMap(x -> countEqual(groupArray(dateDiff('minute', toStartOfInterval(timestamp, INTERVAL 1 MINUTE), toStartOfInterval(now(), INTERVAL 1 MINUTE))), x), range(0,60,1)))
// from cte_timestamps timestamp
