import { UniversalFiltersGroup } from 'lib/components/UniversalFilters/UniversalFilters'
import { dayjs } from 'lib/dayjs'
import { range } from 'lib/utils'

import { DataTableNode, DateRange, ErrorTrackingOrder, EventsQuery, InsightVizNode, NodeKind } from '~/queries/schema'
import { AnyPropertyFilter, BaseMathType, ChartDisplayType } from '~/types'

export type SparklineConfig = {
    value: number
    displayAs: 'minute' | 'hour' | 'day' | 'week' | 'month'
    offsetHours?: number
}

export const SPARKLINE_CONFIGURATIONS: Record<string, SparklineConfig> = {
    '-1d1h': { value: 60, displayAs: 'minute', offsetHours: 24 },
    '-1d24h': { value: 24, displayAs: 'hour', offsetHours: 24 },
    '1h': { value: 60, displayAs: 'minute' },
    '24h': { value: 24, displayAs: 'hour' },
    '7d': { value: 168, displayAs: 'hour' }, // 7d * 24h = 168h
    '14d': { value: 336, displayAs: 'hour' }, // 14d * 24h = 336h
    '90d': { value: 90, displayAs: 'day' },
    '180d': { value: 26, displayAs: 'week' }, // 180d / 7d = 26 weeks
    mStart: { value: 31, displayAs: 'day' },
    yStart: { value: 52, displayAs: 'week' },
}

export const errorTrackingQuery = ({
    order,
    dateRange,
    filterTestAccounts,
    filterGroup,
    sparklineSelectedPeriod,
}: {
    order: ErrorTrackingOrder
    dateRange: DateRange
    filterTestAccounts: boolean
    filterGroup: UniversalFiltersGroup
    sparklineSelectedPeriod: string | null
}): DataTableNode => {
    const select = [
        'any(properties) as "context.columns.error"',
        'properties.$exception_type',
        'count() as occurrences',
        'count(distinct $session_id) as sessions',
        'count(distinct distinct_id) as users',
        'max(timestamp) as last_seen',
        'min(timestamp) as first_seen',
    ]

    const columns = [
        'context.columns.error',
        '$exception_type',
        'occurrences',
        'sessions',
        'users',
        'last_seen',
        'first_seen',
    ]

    if (sparklineSelectedPeriod) {
        const { value, displayAs, offsetHours } = parseSparklineSelection(sparklineSelectedPeriod)
        const { labels, data } = generateSparklineProps({ value, displayAs, offsetHours })

        select.splice(2, 0, `<Sparkline data={${data}} labels={[${labels.join(',')}]} /> as "context.columns.volume"`)
        columns.splice(2, 0, 'context.columns.volume')
    }

    return {
        kind: NodeKind.DataTableNode,
        source: {
            kind: NodeKind.EventsQuery,
            select: select,
            orderBy: [order],
            ...defaultProperties({ dateRange, filterTestAccounts, filterGroup }),
        },
        hiddenColumns: ['$exception_type', 'last_seen', 'first_seen'],
        showActions: false,
        showTimings: false,
        columns: columns,
    }
}

export const parseSparklineSelection = (selection: string): SparklineConfig => {
    if (selection in SPARKLINE_CONFIGURATIONS) {
        return SPARKLINE_CONFIGURATIONS[selection]
    }

    const result = selection.match(/\d+|\D+/g)

    if (result) {
        const [value, unit] = result
        if (unit === 'y') {
            return { value: Number(value) * 12, displayAs: 'month' }
        }
        return {
            value: Number(value),
            displayAs: unit === 'h' ? 'hour' : unit === 'd' ? 'day' : unit === 'w' ? 'week' : 'month',
        }
    }
    return { value: 24, displayAs: 'hour' }
}

export const generateSparklineProps = ({
    value,
    displayAs,
    offsetHours,
}: SparklineConfig): { labels: string[]; data: string } => {
    const offset = offsetHours ?? 0
    const now = dayjs().subtract(offset, 'hours').startOf(displayAs)
    const dates = range(value).map((idx) => now.subtract(value - (idx + 1), displayAs))
    const labels = dates.map((d) => `'${d.format('D MMM, YYYY HH:mm')} (UTC)'`)

    const toStartOfIntervalFn =
        displayAs === 'minute'
            ? 'toStartOfMinute'
            : displayAs === 'hour'
            ? 'toStartOfHour'
            : displayAs === 'day'
            ? 'toStartOfDay'
            : displayAs === 'week'
            ? 'toStartOfWeek'
            : 'toStartOfMonth'
    const data = `reverse(arrayMap(x -> countEqual(groupArray(dateDiff('${displayAs}', ${toStartOfIntervalFn}(timestamp), ${toStartOfIntervalFn}(subtractHours(now(), ${offset})))), x), range(${value})))`

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
