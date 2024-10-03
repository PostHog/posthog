import { UniversalFiltersGroup } from 'lib/components/UniversalFilters/UniversalFilters'
import { dayjs } from 'lib/dayjs'
import { range } from 'lib/utils'

import {
    DataTableNode,
    DateRange,
    ErrorTrackingGroup,
    ErrorTrackingQuery,
    EventsQuery,
    InsightVizNode,
    NodeKind,
} from '~/queries/schema'
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
    assignee,
    filterTestAccounts,
    filterGroup,
    searchQuery,
    sparklineSelectedPeriod,
    columns,
    limit = 50,
}: Pick<ErrorTrackingQuery, 'order' | 'dateRange' | 'assignee' | 'filterTestAccounts' | 'limit' | 'searchQuery'> & {
    filterGroup: UniversalFiltersGroup
    sparklineSelectedPeriod: string | null
    columns: ('error' | 'volume' | 'occurrences' | 'sessions' | 'users' | 'assignee')[]
}): DataTableNode => {
    const select: string[] = []

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
            assignee: assignee,
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
        fingerprint: fingerprint,
        dateRange: dateRange,
        filterGroup: filterGroup as PropertyGroupFilter,
        filterTestAccounts: filterTestAccounts,
    }
}

export const errorTrackingGroupEventsQuery = ({
    select,
    fingerprints,
    dateRange,
    filterTestAccounts,
    filterGroup,
    offset,
}: {
    select: string[]
    fingerprints: ErrorTrackingGroup['fingerprint'][]
    dateRange: DateRange
    filterTestAccounts: boolean
    filterGroup: UniversalFiltersGroup
    offset: number
}): EventsQuery => {
    const group = filterGroup.values[0] as UniversalFiltersGroup
    const properties = group.values as AnyPropertyFilter[]

    const where = [
        `has(${stringifyFingerprints(
            fingerprints
        )}, JSONExtract(ifNull(properties.$exception_fingerprint,'[]'),'Array(String)'))`,
    ]

    const query: EventsQuery = {
        kind: NodeKind.EventsQuery,
        event: '$exception',
        select,
        where,
        properties,
        filterTestAccounts: filterTestAccounts,
        offset: offset,
        limit: 50,
    }

    if (dateRange.date_from) {
        query.after = dateRange.date_from
    }
    if (dateRange.date_to) {
        query.before = dateRange.date_to
    }

    return query
}

// JSON.stringify wraps strings in double quotes and HogQL only supports single quote strings
const stringifyFingerprints = (fingerprints: ErrorTrackingGroup['fingerprint'][]): string => {
    const stringifiedFingerprints = fingerprints.map((fp) => {
        const stringifiedParts = fp.map((s) => `'${s}'`)
        return `[${stringifiedParts.join(',')}]`
    })
    return `[${stringifiedFingerprints.join(',')}]`
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
