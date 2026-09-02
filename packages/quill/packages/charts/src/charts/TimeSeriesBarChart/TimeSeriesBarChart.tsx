import React, { useMemo } from 'react'

import { ChartLegend } from '../../components/Legend/ChartLegend'
import type {
    AxisLinesConfig,
    BarChartConfig,
    BarFillStyle,
    ChartLegendConfig,
    ChartMargins,
    ChartTheme,
    DateRangeZoomData,
    PointClickData,
    Series,
    TooltipConfig,
    TooltipContext,
    ValueDomain,
} from '../../core/types'
import { ReferenceLines } from '../../overlays/ReferenceLine'
import { TrendLineOverlay } from '../../overlays/TrendLineOverlay'
import { ValueLabels } from '../../overlays/ValueLabels'
import { mergeValueDomains, type GoalLineConfig } from '../../utils/goal-lines'
import { useTimeSeriesTooltipConfig, type XAxisConfig, type YAxisConfig } from '../../utils/use-axis-formatters'
import { BarChart } from '../BarChart/BarChart'
import { useTrendLineSeries, type TrendLineConfig } from '../utils/use-derived-series'
import { useGoalLines, useTimeSeries } from '../utils/use-time-series'
import type { ValueLabelsConfig } from '../utils/use-value-labels'

export interface TimeSeriesBarChartConfig {
    xAxis?: XAxisConfig
    /** Single object for a standard left axis; array for dual left+right axes (pass `id` and `position` on each). */
    yAxis?: YAxisConfig | YAxisConfig[]
    valueLabels?: boolean | ValueLabelsConfig
    goalLines?: GoalLineConfig[]
    /** Value-axis domain control — omit for data-derived auto-scaling. A fixed `[min, max]` skips
     *  `d3.nice()` and wins over the goal-line stretch (pin `[0, dataMax]` so the tallest bar
     *  reaches the plot top on an axis-less chart); `{ include }` merges with it. See
     *  {@link ValueDomain}. */
    valueDomain?: ValueDomain
    /** Defaults to `stacked`. */
    barLayout?: BarChartConfig['barLayout']
    /** Defaults to `vertical`. */
    axisOrientation?: BarChartConfig['axisOrientation']
    /** Stacked bars only round the topmost segment. */
    barCornerRadius?: number
    /** Show a vertical crosshair line that follows the cursor. */
    showCrosshair?: boolean
    /** Horizontal grid lines, aligned to the primary y-axis ticks. `showGrid` on the primary
     *  `yAxis` config, when set, wins. */
    showGrid?: boolean
    /** Draw L-shaped axis baselines without grid lines (ignored when `yAxis.showGrid` is true). */
    showAxisLines?: AxisLinesConfig
    /** Draw short tick marks next to each visible axis label. Pairs with `showAxisLines`. */
    showTickMarks?: boolean
    /** Tooltip behaviour (pinning, placement). Tooltip *content* is the `tooltip` render prop. */
    tooltip?: TooltipConfig
    /** Stacked layout only — stack negatives below the zero baseline (d3.stackOffsetDiverging). */
    divergingStack?: boolean
    /** Bar fill treatment — `flat` (default), `gradient`, or `gloss`. */
    fillStyle?: BarFillStyle
    /** Inner gap between bars as a fraction of the band slot (0–1). See {@link BarsConfig.bandPadding}. */
    bandPadding?: number
    /** Px floor on a bar's thickness along the value axis, so a tiny non-zero value stays visible.
     *  See {@link BarsConfig.minBarSize}. */
    minBarSize?: number
    /** Per-side overrides on the computed chart margins — see {@link ChartConfig.margins}. */
    margins?: Partial<ChartMargins>
    /** Ease the hover highlight in over this many ms (`true` = default duration). Omit to snap. */
    animateHover?: boolean | number
    /** Built-in legend with click-to-toggle series visibility. Hidden by default. */
    legend?: ChartLegendConfig
    /** Linear or exponential trend line overlays — rendered as SVG lines on top of the bars. */
    trendLines?: TrendLineConfig[]
}

export interface TimeSeriesBarChartProps<Meta = unknown> {
    series: Series<Meta>[]
    labels: string[]
    theme: ChartTheme
    config?: TimeSeriesBarChartConfig
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    onPointClick?: (data: PointClickData<Meta>) => void
    /** Enables x-axis drag-to-zoom. See `BarChartProps.onDateRangeZoom`. */
    onDateRangeZoom?: (data: DateRangeZoomData) => void
    dataAttr?: string
    className?: string
    children?: React.ReactNode
    onError?: (error: Error, info: React.ErrorInfo) => void
}

export function TimeSeriesBarChart<Meta = unknown>({
    series,
    labels,
    theme,
    config,
    tooltip,
    onPointClick,
    onDateRangeZoom,
    dataAttr,
    className,
    children,
    onError,
}: TimeSeriesBarChartProps<Meta>): React.ReactElement {
    const {
        xAxis,
        yAxis,
        valueLabels,
        goalLines,
        valueDomain,
        barLayout,
        axisOrientation,
        barCornerRadius,
        showCrosshair,
        showGrid,
        showAxisLines,
        showTickMarks,
        tooltip: tooltipConfig,
        divergingStack,
        fillStyle,
        bandPadding,
        minBarSize,
        margins,
        animateHover,
        legend,
        trendLines,
    } = config ?? {}
    const {
        xTickFormatter,
        yTickFormatter,
        legendProps,
        visibleSeries,
        chartSeries,
        valueLabelsConfig,
        valueLabelFormatter,
        primaryYAxis,
        yAxes,
    } = useTimeSeries(series, labels, theme, { xAxis, yAxis, valueLabels, legend })
    const timeSeriesTooltipConfig = useTimeSeriesTooltipConfig(tooltipConfig, xAxis)

    // `axisOrientation` flows through `barChartConfig` into chart context, so `ReferenceLine`
    // reads it automatically — no need to stamp each line here.
    const { referenceLines, valueDomain: goalLineDomain } = useGoalLines(goalLines, chartSeries)
    const resolvedValueDomain = useMemo(
        () => mergeValueDomains(valueDomain, goalLineDomain),
        [valueDomain, goalLineDomain]
    )

    const trendSeries = useTrendLineSeries(visibleSeries, trendLines)

    const barChartConfig: BarChartConfig = {
        margins,
        yScaleType: primaryYAxis?.scale,
        xTickFormatter,
        xTickLabelRotation: xAxis?.tickLabelRotation,
        yTickFormatter,
        hideXAxis: xAxis?.hide,
        hideYAxis: yAxes ? yAxes.length > 0 && yAxes.every((a) => a.hide) : primaryYAxis?.hide,
        xAxisLabel: xAxis?.label,
        yAxisLabel: primaryYAxis?.label,
        showGrid: primaryYAxis?.showGrid ?? showGrid,
        showAxisLines,
        showTickMarks,
        barLayout,
        axisOrientation,
        showCrosshair,
        tooltip: timeSeriesTooltipConfig,
        animateHover,
        yAxes,
        barCornerRadius,
        bars: {
            divergingStack,
            valueDomain: resolvedValueDomain,
            fillStyle,
            bandPadding,
            minBarSize,
        },
    }

    return (
        <ChartLegend {...legendProps} legendDataAttr="hog-chart-timeseries-bar-legend">
            <BarChart
                series={chartSeries}
                labels={labels}
                config={barChartConfig}
                theme={theme}
                tooltip={tooltip}
                onPointClick={onPointClick}
                onDateRangeZoom={onDateRangeZoom}
                className={className}
                dataAttr={dataAttr}
                onError={onError}
            >
                {referenceLines.length > 0 && <ReferenceLines lines={referenceLines} />}
                {trendSeries.length > 0 && <TrendLineOverlay trendSeries={trendSeries} />}
                {valueLabelsConfig && <ValueLabels valueFormatter={valueLabelFormatter} />}
                {children}
            </BarChart>
        </ChartLegend>
    )
}
