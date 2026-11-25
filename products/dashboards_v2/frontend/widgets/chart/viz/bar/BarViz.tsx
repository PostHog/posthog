import { useMemo, useRef } from 'react'

import { TimeSeriesBarChart, type TimeSeriesBarChartConfig } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'

import { timeSeriesFromFrames, yAxisFor } from '../../timeSeriesFrames'
import type { DataFrame } from '../../vizTypes'
import type { BarOptions } from './barSpec'

export function BarViz({ frames, options }: { frames: DataFrame[]; options: BarOptions }): JSX.Element {
    const theme = useChartTheme()
    const assignedColors = useRef(new Map<string, string>())
    const { labels, series, axes } = useMemo(
        () => timeSeriesFromFrames(frames, theme.colors, assignedColors.current),
        [frames, theme.colors]
    )
    const stacked = !!options.stack
    const config = useChartConfig<TimeSeriesBarChartConfig>(
        () => ({
            barLayout: stacked ? 'stacked' : 'grouped',
            xAxis: { allDays: labels },
            yAxis: yAxisFor(axes),
            legend: { show: series.length > 1, position: 'top' },
            tooltip: { placement: 'cursor', sortedByValue: true },
        }),
        [labels, series.length, stacked, axes]
    )
    return (
        <div className="relative flex min-h-0 w-full flex-1 flex-col">
            <TimeSeriesBarChart series={series} labels={labels} theme={theme} config={config} />
        </div>
    )
}
