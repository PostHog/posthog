import { useValues } from 'kea'
import { useMemo } from 'react'

import { TimeSeriesLineChart } from '@posthog/quill-charts'
import type { Series, TimeSeriesLineChartConfig } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

import { hourTick } from './evaluationOverviewDisplay'
import { evaluationsOverviewLogic } from './evaluationsOverviewLogic'

export function EvaluationOverviewMetricChart({
    label,
    labels,
    values,
    color,
    percentage = false,
}: {
    label: string
    labels: string[]
    values: number[]
    color?: string
    percentage?: boolean
}): JSX.Element {
    const theme = useChartTheme()
    const { timezone, interval } = useValues(evaluationsOverviewLogic)
    const series = useMemo<Series[]>(
        () => [{ key: 'metric', label, data: values, color, points: { radius: 3 } }],
        [label, values, color]
    )
    const config = useMemo<TimeSeriesLineChartConfig>(
        () => ({
            xAxis: { timezone, interval, ...(interval === 'hour' ? { tickFormatter: hourTick } : {}) },
            yAxis: percentage ? { format: 'percentage', showGrid: true } : { showGrid: true, decimalPlaces: 0 },
            showCrosshair: true,
            // Straight segments, because a curve invents values between buckets and overshoots on sparse ones.
            curve: 'linear',
        }),
        [percentage, timezone, interval]
    )
    return (
        <div className="h-64 min-w-0 flex flex-col">
            <TimeSeriesLineChart series={series} labels={labels} theme={theme} config={config} />
        </div>
    )
}
