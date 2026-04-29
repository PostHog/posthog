import { useMemo } from 'react'

import { buildTheme } from 'lib/charts/utils/theme'
import { LineChart } from 'lib/hog-charts'
import type { LineChartConfig, Series } from 'lib/hog-charts'

import type { BenchData } from './generateBenchData'

interface HogChartsLineChartProps {
    data: BenchData
    fillArea: boolean
    showGrid: boolean
}

const CONFIG: LineChartConfig = {
    showGrid: true,
    showCrosshair: true,
}

export function HogChartsLineChart({ data, fillArea, showGrid }: HogChartsLineChartProps): JSX.Element {
    const theme = useMemo(() => buildTheme(), [])

    const series: Series[] = useMemo(
        () =>
            data.series.map((s, idx) => ({
                key: s.key,
                label: s.label,
                data: s.data,
                // LineChart auto-assigns colors when `color` is an empty string via the theme,
                // but Series requires a color — pick from the theme palette ourselves.
                color: theme.colors[idx % theme.colors.length],
                fillArea,
            })),
        [data.series, fillArea, theme.colors]
    )

    const config: LineChartConfig = useMemo(() => ({ ...CONFIG, showGrid }), [showGrid])

    return (
        <div className="flex flex-col flex-1 min-h-0" data-attr="hog-charts-bench">
            <LineChart series={series} labels={data.labels} config={config} theme={theme} />
        </div>
    )
}
