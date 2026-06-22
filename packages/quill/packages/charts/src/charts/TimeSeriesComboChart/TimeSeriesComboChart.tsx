import React, { useMemo } from 'react'

import { ChartLegend } from '../../components/Legend/ChartLegend'
import { useChartLegend } from '../../components/Legend/useChartLegend'
import type {
    ChartLegendConfig,
    ChartTheme,
    ComboChartConfig,
    PointClickData,
    SeriesType,
    Series,
    TooltipConfig,
    TooltipContext,
} from '../../core/types'
import { ReferenceLines } from '../../overlays/ReferenceLine'
import { ValueLabels } from '../../overlays/ValueLabels'
import { buildGoalLineReferenceLines, goalLineValueDomain, type GoalLineConfig } from '../../utils/goal-lines'
import {
    useXTickFormatter,
    useYTickFormatter,
    type XAxisConfig,
    type YAxisConfig,
} from '../../utils/use-axis-formatters'
import { ComboChart } from '../ComboChart/ComboChart'
import {
    resolveValueLabelsConfig,
    useSeriesWithValueLabelAllowlist,
    type ValueLabelsConfig,
} from '../utils/use-value-labels'

export interface TimeSeriesComboChartConfig {
    xAxis?: XAxisConfig
    yAxis?: YAxisConfig
    valueLabels?: boolean | ValueLabelsConfig
    goalLines?: GoalLineConfig[]
    /** Type used for series that don't set {@link Series.type}. Defaults to `'line'`. */
    defaultSeriesType?: SeriesType
    /** Layout applied to *bar* series only — lines and areas never stack or group. Defaults to
     *  `'stacked'`. */
    barLayout?: ComboChartConfig['barLayout']
    /** Stacked bars only round the topmost segment. */
    barCornerRadius?: number
    /** Show a vertical crosshair line that follows the cursor. */
    showCrosshair?: boolean
    /** Draw L-shaped axis baselines without grid lines (ignored when `yAxis.showGrid` is true). */
    showAxisLines?: boolean
    /** Tooltip behaviour (pinning, placement). Tooltip *content* is the `tooltip` render prop. */
    tooltip?: TooltipConfig
    /** Built-in legend with click-to-toggle series visibility. Hidden by default. */
    legend?: ChartLegendConfig
}

export interface TimeSeriesComboChartProps<Meta = unknown> {
    series: Series<Meta>[]
    labels: string[]
    theme: ChartTheme
    config?: TimeSeriesComboChartConfig
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    onPointClick?: (data: PointClickData<Meta>) => void
    dataAttr?: string
    className?: string
    children?: React.ReactNode
    onError?: (error: Error, info: React.ErrorInfo) => void
}

/** Time-indexed {@link ComboChart}: mixed bar + line/area series on a timezone/interval-aware band
 *  x-axis, plus the time-series chrome `ComboChart` lacks — date x-axis, goal lines, a built-in
 *  legend, and value labels. Mirrors {@link TimeSeriesBarChart}/{@link TimeSeriesLineChart}. */
export function TimeSeriesComboChart<Meta = unknown>({
    series,
    labels,
    theme,
    config,
    tooltip,
    onPointClick,
    dataAttr,
    className,
    children,
    onError,
}: TimeSeriesComboChartProps<Meta>): React.ReactElement {
    const {
        xAxis,
        yAxis,
        valueLabels,
        goalLines,
        defaultSeriesType,
        barLayout,
        barCornerRadius,
        showCrosshair,
        showAxisLines,
        tooltip: tooltipConfig,
        legend,
    } = config ?? {}
    const xTickFormatter = useXTickFormatter(xAxis, labels)
    const yTickFormatter = useYTickFormatter(yAxis)

    const { visibleSeries, legendProps } = useChartLegend(series, theme, legend)

    const valueLabelsConfig = resolveValueLabelsConfig(valueLabels)
    const seriesAfterValueLabels = useSeriesWithValueLabelAllowlist(visibleSeries, valueLabelsConfig?.seriesKeys)

    const valueLabelFormatter = valueLabelsConfig ? (valueLabelsConfig.formatter ?? yTickFormatter) : undefined

    const referenceLines = useMemo(
        () => buildGoalLineReferenceLines(goalLines, seriesAfterValueLabels),
        [goalLines, seriesAfterValueLabels]
    )

    // Extend the value axis to cover goal lines that sit outside the data range, so a goal line
    // off the data's natural scale still renders inside the plot. Memoized so the `{ include }`
    // object stays referentially stable and doesn't re-trigger scale recomputation each render.
    const valueDomain = useMemo(() => goalLineValueDomain(referenceLines), [referenceLines])

    const comboChartConfig: ComboChartConfig = {
        yScaleType: yAxis?.scale,
        xTickFormatter,
        yTickFormatter,
        hideXAxis: xAxis?.hide,
        hideYAxis: yAxis?.hide,
        xAxisLabel: xAxis?.label,
        yAxisLabel: yAxis?.label,
        showGrid: yAxis?.showGrid,
        showAxisLines,
        showCrosshair,
        defaultSeriesType,
        barLayout,
        barCornerRadius,
        tooltip: tooltipConfig,
        valueDomain,
    }

    return (
        <ChartLegend {...legendProps} legendDataAttr="hog-chart-timeseries-combo-legend">
            <ComboChart
                series={seriesAfterValueLabels}
                labels={labels}
                config={comboChartConfig}
                theme={theme}
                tooltip={tooltip}
                onPointClick={onPointClick}
                className={className}
                dataAttr={dataAttr}
                onError={onError}
            >
                {referenceLines.length > 0 && <ReferenceLines lines={referenceLines} />}
                {valueLabelsConfig && <ValueLabels valueFormatter={valueLabelFormatter} />}
                {children}
            </ComboChart>
        </ChartLegend>
    )
}
