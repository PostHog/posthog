import { useMemo } from 'react'

import {
    AnomalyPointsLayer,
    DEFAULT_Y_AXIS_ID,
    LineChart,
    type LineChartConfig,
    ReferenceLine,
    type Series,
} from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { type TodayTone, useTodayTonePalette } from 'scenes/project-homepage/today/todayTone'

export function BetSparkline({
    label,
    values,
    labels,
    limit,
    floor,
    tone,
}: {
    label: string
    values: number[]
    labels: string[]
    limit: number | null
    floor?: number
    tone: TodayTone
}): JSX.Element {
    const theme = useChartTheme()
    const palette = useTodayTonePalette()
    const last = values.length - 1
    const lineColor = theme.axisColor ?? palette.neutral
    const series = useMemo<Series[]>(
        () => [{ key: 'value', label, data: values, color: lineColor }],
        [label, values, lineColor]
    )
    const known = [...values, ...(limit === null ? [] : [limit]), ...(floor === undefined ? [] : [floor])]
    const minimum = known.length ? Math.min(...known) : 0
    const maximum = known.length ? Math.max(...known) : 1
    const padding = Math.max((maximum - minimum) * 0.12, Math.abs(maximum) * 0.04, 0.01)
    const config = useChartConfig<LineChartConfig>(
        () => ({
            hideXAxis: true,
            hideYAxis: true,
            showGrid: false,
            showAxisLines: false,
            showTickMarks: false,
            showCrosshair: false,
            curve: 'linear',
            margins: { top: 3, right: 4, bottom: 3, left: 1 },
            valueDomain: { min: floor === undefined ? minimum - padding : floor, max: maximum + padding },
            tooltip: { enabled: false },
        }),
        [floor, minimum, maximum, padding]
    )
    return (
        <div className="h-8 w-full" role="img" aria-label={label}>
            <LineChart series={series} labels={labels} theme={theme} config={config} className="h-full w-full">
                {limit !== null && (
                    <ReferenceLine value={limit} orientation="horizontal" variant="marker" showValueOnHover={false} />
                )}
                <AnomalyPointsLayer
                    radius={2.5}
                    markers={
                        last >= 0
                            ? [
                                  {
                                      dataIndex: last,
                                      value: values[last],
                                      color: tone === 'neutral' ? lineColor : palette[tone],
                                      yAxisId: DEFAULT_Y_AXIS_ID,
                                  },
                              ]
                            : []
                    }
                />
            </LineChart>
        </div>
    )
}
