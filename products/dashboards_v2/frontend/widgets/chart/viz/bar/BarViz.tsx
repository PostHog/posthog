import { TimeSeriesBarChart, type TimeSeriesBarChartConfig } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'

import { timeSeriesFromFrames } from '../../timeSeriesFrames'
import type { DataFrame } from '../../vizTypes'
import type { BarOptions } from './barSpec'

export function BarViz({ frames, options }: { frames: DataFrame[]; options: BarOptions }): JSX.Element {
    const theme = useChartTheme()
    const { labels, series } = timeSeriesFromFrames(frames)
    const stacked = !!options.stack
    const config = useChartConfig<TimeSeriesBarChartConfig>(
        () => ({
            barLayout: stacked ? 'stacked' : 'grouped',
            xAxis: { allDays: labels },
            yAxis: { showGrid: true },
            legend: { show: series.length > 1, position: 'top' },
            tooltip: { placement: 'cursor', sortedByValue: true },
        }),
        [labels, series.length, stacked]
    )
    return (
        <div className="relative flex min-h-0 w-full flex-1 flex-col">
            <TimeSeriesBarChart series={series} labels={labels} theme={theme} config={config} />
        </div>
    )
}
