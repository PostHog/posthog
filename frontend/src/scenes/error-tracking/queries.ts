import { UniversalFiltersGroup } from 'lib/components/UniversalFilters/UniversalFilters'
import { dayjs } from 'lib/dayjs'
import { range } from 'lib/utils'

import { DataTableNode, DateRange, ErrorTrackingOrder, EventsQuery, InsightVizNode, NodeKind } from '~/queries/schema'
import { AnyPropertyFilter, BaseMathType, ChartDisplayType } from '~/types'

import { SparklineOption } from './errorTrackingLogic'

export type ErrorTrackingSparklineConfig = {
    value: number
    displayAs: 'minute' | 'hour' | 'day'
    offsetHours?: number
}

export const SPARKLINE_CONFIGURATIONS: Record<string, ErrorTrackingSparklineConfig> = {
    '1h': { value: 60, displayAs: 'minute' },
    '24h': { value: 24, displayAs: 'hour' },
    '7d': { value: 168, displayAs: 'hour' }, // 7d * 24h = 168h
    '14d': { value: 336, displayAs: 'hour' }, // 14d * 24h = 336h
    '90d': { value: 90, displayAs: 'day' },
    '180d': { value: 180, displayAs: 'day' },
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
    sparklineSelection: SparklineOption
}): DataTableNode => {
    const { value, displayAs, offsetHours } = parseSelection(sparklineSelection)

    const { labels, data } = generateSparklineProps({ value, displayAs, offsetHours })

    return {
        kind: NodeKind.DataTableNode,
        source: {
            kind: NodeKind.EventsQuery,
            select: [
                'any(properties) as "context.columns.error"',
                'properties.$exception_type',
                `<Sparkline data={${data}} labels={[${labels.join(',')}]} /> as "context.columns.volume"`,
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

const parseSelection = (selection: SparklineOption): ErrorTrackingSparklineConfig => {
    if (selection.value in SPARKLINE_CONFIGURATIONS) {
        return { ...selection, ...SPARKLINE_CONFIGURATIONS[selection.value] }
    }

    const [value, unit] = selection.value.replace('-', '').split('')

    return {
        ...selection,
        value: Number(value),
        displayAs: unit === 'm' ? 'minute' : unit === 'h' ? 'hour' : 'day',
        gap: 1,
    }
}

export const generateSparklineProps = ({
    value,
    displayAs,
    offsetHours,
}: ErrorTrackingSparklineConfig): { labels: string[]; data: string } => {
    const offset = offsetHours ?? 0
    const now = dayjs().subtract(offset, 'hour').startOf(displayAs)
    const dates = range(value).map((idx) => now.subtract(value - (idx + 1), displayAs))
    const labels = dates.map((d) => `'${d.format('D MMM, YYYY HH:mm')} (UTC)'`)

    const startTime = `subtractHours(now(), ${offset})`
    const toStartOfIntervalFn =
        displayAs === 'minute' ? 'toStartOfMinute' : displayAs === 'hour' ? 'toStartOfHour' : 'toStartOfDay'
    const data = `reverse(arrayMap(x -> countEqual(groupArray(dateDiff('${displayAs}', ${toStartOfIntervalFn}(timestamp), ${toStartOfIntervalFn}(${startTime}))), x), range(${value})))`

    return { labels, data }
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
