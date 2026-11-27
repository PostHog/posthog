import { useMemo, useRef } from 'react'

import { TimeSeriesBarChart, type TimeSeriesBarChartConfig } from '@posthog/quill-charts'

import { useChartConfig } from 'lib/charts/hooks'

import type { DataFrame } from '../../../../query/queryTypes'
import { timeSeriesFromFrames, yAxisFor } from '../../data/timeSeriesFrames'
import { useSharedChartTheme } from '../../useSharedChartTheme'
import type { BarOptions } from './barSpec'

export function BarViz({ frames, options }: { frames: DataFrame[]; options: BarOptions }): JSX.Element {
    const theme = useSharedChartTheme()
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
            yAxis: yAxisFor(axes, series),
            legend: { show: series.length > 1, position: 'top' },
            tooltip: { placement: 'cursor', sortedByValue: true },
        }),
        [labels, series, stacked, axes]
    )
    return (
        <div className="relative flex min-h-0 w-full flex-1 flex-col">
            <TimeSeriesBarChart series={series} labels={labels} theme={theme} config={config} />
        </div>
    )
}
