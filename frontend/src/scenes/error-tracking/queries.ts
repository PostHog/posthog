import { UniversalFiltersGroup } from 'lib/components/UniversalFilters/UniversalFilters'
import { dayjs } from 'lib/dayjs'
import { range } from 'lib/utils'

import { DataTableNode, DateRange, ErrorTrackingQuery, InsightVizNode, NodeKind } from '~/queries/schema'
import { AnyPropertyFilter, BaseMathType, ChartDisplayType, PropertyGroupFilter } from '~/types'

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

const toStartOfIntervalFn = {
    minute: 'toStartOfMinute',
    hour: 'toStartOfHour',
    day: 'toStartOfDay',
    week: 'toStartOfWeek',
    month: 'toStartOfMonth',
}

export const errorTrackingQuery = ({
    order,
    dateRange,
    filterTestAccounts,
    filterGroup,
    sparklineSelectedPeriod,
    columns,
    limit = 50,
}: {
    order: ErrorTrackingQuery['order']
    dateRange: DateRange
    filterTestAccounts: boolean
    filterGroup: UniversalFiltersGroup
    sparklineSelectedPeriod: string | null
    columns?: ('error' | 'volume' | 'occurrences' | 'sessions' | 'users' | 'assignee')[]
    limit?: number
}): DataTableNode => {
    const select: string[] = []
    if (!columns) {
        columns = ['error', 'occurrences', 'sessions', 'users', 'assignee']
    }

    if (sparklineSelectedPeriod) {
        const { value, displayAs, offsetHours } = parseSparklineSelection(sparklineSelectedPeriod)
        const { labels, data } = generateSparklineProps({ value, displayAs, offsetHours })

        select.splice(1, 0, `<Sparkline data={${data}} labels={[${labels.join(',')}]} /> as volume`)
        columns.splice(1, 0, 'volume')
    }

    return {
        kind: NodeKind.DataTableNode,
        source: {
            kind: NodeKind.ErrorTrackingQuery,
            select: select,
            order: order,
            dateRange: dateRange,
            filterGroup: filterGroup as PropertyGroupFilter,
            filterTestAccounts: filterTestAccounts,
            limit: limit,
        },
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

        return {
            value: Number(value) * (unit === 'y' ? 12 : 1),
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

    const toStartOfInterval = toStartOfIntervalFn[displayAs]
    const data = `reverse(arrayMap(x -> countEqual(groupArray(dateDiff('${displayAs}', ${toStartOfInterval}(timestamp), ${toStartOfInterval}(subtractHours(now(), ${offset})))), x), range(${value})))`

    return { labels, data }
}

export const errorTrackingGroupQuery = ({
    fingerprint,
    dateRange,
    filterTestAccounts,
    filterGroup,
}: {
    fingerprint: string[]
    dateRange: DateRange
    filterTestAccounts: boolean
    filterGroup: UniversalFiltersGroup
}): ErrorTrackingQuery => {
    return {
        kind: NodeKind.ErrorTrackingQuery,
        eventColumns: ['uuid', 'properties', 'timestamp', 'person'],
        fingerprint: fingerprint,
        dateRange: dateRange,
        filterGroup: filterGroup as PropertyGroupFilter,
        filterTestAccounts: filterTestAccounts,
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
