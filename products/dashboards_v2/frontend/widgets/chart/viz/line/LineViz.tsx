import { useMemo, useRef } from 'react'

import { TimeSeriesLineChart, type TimeSeriesLineChartConfig } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'

import { timeSeriesFromFrames, yAxisFor } from '../../timeSeriesFrames'
import type { DataFrame } from '../../vizTypes'
import type { LineOptions } from './lineSpec'

export function LineViz({ frames }: { frames: DataFrame[]; options: LineOptions }): JSX.Element {
    const theme = useChartTheme()
    const assignedColors = useRef(new Map<string, string>())
    const { labels, series, axes, multiTarget } = useMemo(
        () => timeSeriesFromFrames(frames, theme.colors, assignedColors.current),
        [frames, theme.colors]
    )
    const config = useChartConfig<TimeSeriesLineChartConfig>(
        () => ({
            xAxis: { allDays: labels },
            yAxis: yAxisFor(axes),
            legend: { show: series.length > 1, position: 'top' },
            tooltip: { placement: 'cursor', sortedByValue: true },
            // Targets in other languages sample on their own steps, so a series is drawn across the others' points.
            connectNulls: multiTarget,
            // Their merged timestamps are unevenly spaced, so each point sits at its time rather than its index.
            ...(multiTarget ? { xScale: 'time' as const } : {}),
        }),
        [labels, series.length, axes, multiTarget]
    )
    return (
        <div className="relative flex min-h-0 w-full flex-1 flex-col">
            <TimeSeriesLineChart series={series} labels={labels} theme={theme} config={config} />
        </div>
    )
}
