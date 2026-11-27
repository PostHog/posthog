import { useCallback, useContext, useMemo, useRef } from 'react'

import { type TimeSeriesLineChartConfig, useResolvedChartTheme } from '@posthog/quill-charts'

import { FilterControlsContext } from '../../../filters/filtersContext'
import type { TimeRange } from '../../../filters/time/timeRangeSchema'
import type { DataFrame } from '../../../query/queryTypes'
import { type TimeSeriesData, timeSeriesFromFrames, yAxisFor } from './timeSeriesFrames'

type BaseConfig = Pick<TimeSeriesLineChartConfig, 'xAxis' | 'yAxis' | 'legend' | 'tooltip'>

/** The series and the axes, legend and tooltip that every time-series kind of chart shares. */
export function useTimeSeriesChart(frames: DataFrame[]): TimeSeriesData & { baseConfig: BaseConfig } {
    const theme = useResolvedChartTheme()
    const assignedColors = useRef(new Map<string, string>())
    const data = useMemo(
        () => timeSeriesFromFrames(frames, theme.colors, assignedColors.current),
        [frames, theme.colors]
    )
    const baseConfig = useMemo(
        (): BaseConfig => ({
            xAxis: { allDays: data.labels },
            yAxis: yAxisFor(data.axes, data.series),
            legend: { show: data.series.length > 1, position: 'top' },
            tooltip: { placement: 'cursor', sortedByValue: true },
        }),
        [data]
    )
    return { ...data, baseConfig }
}

const DAY_MS = 24 * 60 * 60 * 1000

// Months differ in length, so a bucket's end steps by its interval rather than copying the previous bucket's length.
function bucketEnd(start: number, interval: string | null | undefined): number | undefined {
    const date = new Date(start)
    switch (interval) {
        case 'minute':
            return start + 60 * 1000
        case 'hour':
            return start + 60 * 60 * 1000
        case 'day':
            return start + DAY_MS
        case 'week':
            return start + 7 * DAY_MS
        case 'month':
            return date.setUTCMonth(date.getUTCMonth() + 1)
        default:
            return undefined
    }
}

/**
 * The dragged buckets as a time range. Each label is a bucket's start, so the range ends where the last bucket ends.
 * Date labels give an inclusive last day, as PostHog reads a date `to` through the end of that day.
 */
export function zoomedTimeRange(
    labels: string[],
    startIndex: number,
    endIndex: number,
    interval?: string | null
): TimeRange | undefined {
    const start = Date.parse(labels[startIndex])
    const lastStart = Date.parse(labels[endIndex])
    if (Number.isNaN(start) || Number.isNaN(lastStart)) {
        return undefined
    }
    const next = Date.parse(labels[endIndex + 1] ?? '')
    const previous = Date.parse(labels[endIndex - 1] ?? '')
    const end =
        bucketEnd(lastStart, interval) ??
        (Number.isNaN(next) ? lastStart + (Number.isNaN(previous) ? DAY_MS : lastStart - previous) : next)
    // Date labels stay dates, so the range reads in the project's timezone rather than as UTC midnight.
    if (!labels[startIndex].includes('T')) {
        return { from: labels[startIndex], to: new Date(end - DAY_MS).toISOString().slice(0, 10) }
    }
    return { from: new Date(start).toISOString(), to: new Date(end).toISOString() }
}

export function useZoomToTimeRange(
    labels: string[],
    interval?: string | null
): ((range: { startIndex: number; endIndex: number }) => void) | undefined {
    const { timeRange } = useContext(FilterControlsContext)
    const onChange = timeRange?.onChange
    const onZoom = useCallback(
        ({ startIndex, endIndex }: { startIndex: number; endIndex: number }) => {
            const range = zoomedTimeRange(labels, startIndex, endIndex, interval)
            if (range) {
                onChange?.(range)
            }
        },
        [labels, interval, onChange]
    )
    return onChange ? onZoom : undefined
}
