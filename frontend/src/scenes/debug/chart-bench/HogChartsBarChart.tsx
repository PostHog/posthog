import { useMemo } from 'react'

import { buildTheme } from 'lib/charts/utils/theme'
import { TimeSeriesBarChart } from 'lib/hog-charts'
import type { Series, TimeSeriesBarChartConfig } from 'lib/hog-charts'

import type { BenchData } from './generateBenchData'

interface HogChartsBarChartProps {
    data: BenchData
    showGrid: boolean
    /** Render time buckets down the y-axis with bars extending horizontally. */
    horizontal?: boolean
}

const CONFIG: TimeSeriesBarChartConfig = {
    showCrosshair: true,
}

/**
 * Raw `lib/hog-charts` TimeSeriesBarChart, synthetic data. Mirrors
 * {@link HogChartsLineChart} so the bar engine cost can be compared against the
 * line engine on identical input. `fillArea` is meaningless for bars; the grid
 * toggle drives the axis grid lines. The same time-series data renders either
 * vertically (default) or horizontally — only the axis orientation differs, so
 * the two are a clean rotated-vs-upright comparison.
 */
export function HogChartsBarChart({ data, showGrid, horizontal = false }: HogChartsBarChartProps): JSX.Element {
    const theme = useMemo(() => buildTheme(), [])

    const series: Series[] = useMemo(
        () =>
            data.series.map((s, idx) => ({
                key: s.key,
                label: s.label,
                data: s.data,
                color: theme.colors[idx % theme.colors.length],
            })),
        [data.series, theme.colors]
    )

    const config: TimeSeriesBarChartConfig = useMemo(
        () => ({ ...CONFIG, yAxis: { showGrid }, axisOrientation: horizontal ? 'horizontal' : 'vertical' }),
        [showGrid, horizontal]
    )

    return (
        <div className="flex flex-col flex-1 min-h-0" data-attr="hog-charts-bar-bench">
            <TimeSeriesBarChart series={series} labels={data.labels} config={config} theme={theme} />
        </div>
    )
}
