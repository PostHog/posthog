import { dayjs } from 'lib/dayjs'
import { hasTimeComponent } from 'scenes/insights/insightVizDataLogic'

import { isFunnelsQuery, isInsightVizNode, isLifecycleQuery, isTrendsQuery } from '~/queries/schema/node-guards'
import { ChartDisplayType, InsightModel } from '~/types'

export interface ZoomRange {
    dateFrom: string
    dateTo: string
}

type TimeSeries = { days: string[]; data: number[] } & Record<string, unknown>

// Arrays with one entry per bucket. Others, such as a multi-breakdown `breakdown_value`, can match the
// bucket count by chance and must not be cut.
const PER_BUCKET_KEYS = ['days', 'data', 'labels', 'reached_from_step_count', 'reached_to_step_count']

const TIME_SERIES_DISPLAYS = new Set<ChartDisplayType | undefined>([
    undefined,
    ChartDisplayType.ActionsLineGraph,
    ChartDisplayType.ActionsAreaGraph,
    ChartDisplayType.ActionsBar,
])

/** Which results can be cropped to a narrower date range and still show what the server would return
 *  for it. Values per time bucket qualify. Totals over the range (numbers, pies, funnel steps) and
 *  values that depend on where the range starts (moving averages, cumulative lines) don't. */
type CroppableKind = 'buckets' | 'funnel_trends'

function croppableKind(insight: InsightModel): CroppableKind | null {
    const query = insight.query
    if (!isInsightVizNode(query)) {
        return null
    }
    const source = query.source
    if (isTrendsQuery(source)) {
        const filter = source.trendsFilter
        if (!TIME_SERIES_DISPLAYS.has(filter?.display) || (filter?.smoothingIntervals ?? 1) > 1) {
            return null
        }
        return 'buckets'
    }
    if (isLifecycleQuery(source)) {
        return 'buckets'
    }
    if (isFunnelsQuery(source) && source.funnelsFilter?.funnelVizType === 'trends') {
        return 'funnel_trends'
    }
    return null
}

function isTimeSeries(value: unknown): value is TimeSeries {
    return (
        !!value &&
        typeof value === 'object' &&
        Array.isArray((value as TimeSeries).days) &&
        Array.isArray((value as TimeSeries).data)
    )
}

/** Index range of the buckets that overlap the zoom range. Partly covered edge buckets stay, so the
 *  axis spans the whole selection even when this tile's interval is coarser than the dragged one. */
function overlappingBuckets(days: string[], range: ZoomRange): [number, number] | null {
    const from = dayjs(range.dateFrom)
    const to = hasTimeComponent(range.dateTo) ? dayjs(range.dateTo) : dayjs(range.dateTo).endOf('day')
    const starts = days.map((day) => dayjs(day))
    let first = -1
    let last = -1
    for (let i = 0; i < starts.length; i++) {
        const start = starts[i]
        const end =
            i + 1 < starts.length
                ? starts[i + 1]
                : i > 0
                  ? start.add(start.diff(starts[i - 1]), 'millisecond')
                  : start.endOf('day')
        if (!start.isAfter(to) && end.isAfter(from)) {
            first = first === -1 ? i : first
            last = i
        }
    }
    return first === -1 ? null : [first, last]
}

function cropSeries(series: TimeSeries, [first, last]: [number, number], kind: CroppableKind): TimeSeries {
    const cropped: TimeSeries = { ...series }
    for (const key of PER_BUCKET_KEYS) {
        const value = series[key]
        if (Array.isArray(value)) {
            cropped[key] = value.slice(first, last + 1)
        }
    }
    // Matches how the server counts each kind: the number of buckets for funnel trends, else the sum.
    cropped.count = kind === 'funnel_trends' ? cropped.data.length : cropped.data.reduce((sum, value) => sum + value, 0)
    return cropped
}

export function cropInsightToZoom(insight: InsightModel, range: ZoomRange): InsightModel {
    const kind = croppableKind(insight)
    const result: unknown = insight.result
    if (!kind || !Array.isArray(result) || !result.length || !result.every(isTimeSeries)) {
        return insight
    }
    const days = result[0].days
    // A previous period moves with the zoom rather than being cut at the same positions, so a
    // comparison has no correct crop.
    if (result.some((series) => series.compare_label || series.days.length !== days.length)) {
        return insight
    }
    const bounds = overlappingBuckets(days, range)
    if (!bounds || (bounds[0] === 0 && bounds[1] === days.length - 1)) {
        return insight
    }
    return { ...insight, result: result.map((series) => cropSeries(series, bounds, kind)) }
}
