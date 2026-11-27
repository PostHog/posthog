import { useMemo, useRef } from 'react'

import { type TimeSeriesLineChartConfig, useResolvedChartTheme } from '@posthog/quill-charts'

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
