import { TimeSeriesLineChart, type TimeSeriesLineChartConfig } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'

import { timeSeriesFromFrames } from '../../timeSeriesFrames'
import type { DataFrame } from '../../vizTypes'
import type { LineOptions } from './lineSpec'

export function LineViz({ frames }: { frames: DataFrame[]; options: LineOptions }): JSX.Element {
    const theme = useChartTheme()
    const { labels, series } = timeSeriesFromFrames(frames)
    const config = useChartConfig<TimeSeriesLineChartConfig>(
        () => ({
            xAxis: { allDays: labels },
            yAxis: { showGrid: true },
            legend: { show: series.length > 1, position: 'top' },
            tooltip: { placement: 'cursor', sortedByValue: true },
        }),
        [labels, series.length]
    )
    return (
        <div className="relative flex min-h-0 w-full flex-1 flex-col">
            <TimeSeriesLineChart series={series} labels={labels} theme={theme} config={config} />
        </div>
    )
}
