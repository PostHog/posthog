import React, { useMemo } from 'react'

import { ChartLegend } from '../../components/Legend/ChartLegend'
import { useChartLegend } from '../../components/Legend/useChartLegend'
import type {
    BarChartConfig,
    BarFillStyle,
    ChartLegendConfig,
    ChartTheme,
    PointClickData,
    Series,
    TooltipConfig,
    TooltipContext,
} from '../../core/types'
import { ReferenceLines } from '../../overlays/ReferenceLine'
import { TrendLineOverlay } from '../../overlays/TrendLineOverlay'
import { ValueLabels } from '../../overlays/ValueLabels'
import { buildGoalLineReferenceLines, goalLineValueDomain, type GoalLineConfig } from '../../utils/goal-lines'
import {
    buildYAxes,
    normalizeYAxisList,
    primaryYAxisConfig,
    useXTickFormatter,
    useYTickFormatter,
    type XAxisConfig,
    type YAxisConfig,
} from '../../utils/use-axis-formatters'
import { BarChart } from '../BarChart/BarChart'
import { buildTrendLineSeries, type TrendLineConfig } from '../TimeSeriesLineChart/utils/derived-series'
import {
    resolveValueLabelsConfig,
    useSeriesWithValueLabelAllowlist,
    type ValueLabelsConfig,
} from '../utils/use-value-labels'

export interface TimeSeriesBarChartConfig {
    xAxis?: XAxisConfig
    /** Single object for a standard left axis; array for dual left+right axes (pass `id` and `position` on each). */
    yAxis?: YAxisConfig | YAxisConfig[]
    valueLabels?: boolean | ValueLabelsConfig
    goalLines?: GoalLineConfig[]
    /** Defaults to `stacked`. */
    barLayout?: BarChartConfig['barLayout']
    /** Defaults to `vertical`. */
    axisOrientation?: BarChartConfig['axisOrientation']
    /** Stacked bars only round the topmost segment. */
    barCornerRadius?: number
    /** Show a vertical crosshair line that follows the cursor. */
    showCrosshair?: boolean
    /** Draw L-shaped axis baselines without grid lines (ignored when `yAxis.showGrid` is true). */
    showAxisLines?: boolean
    /** Tooltip behaviour (pinning, placement). Tooltip *content* is the `tooltip` render prop. */
    tooltip?: TooltipConfig
    /** Stacked layout only — stack negatives below the zero baseline (d3.stackOffsetDiverging). */
    divergingStack?: boolean
    /** Bar fill treatment — `flat` (default), `gradient`, or `gloss`. */
    fillStyle?: BarFillStyle
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
        barLayout,
        axisOrientation,
        barCornerRadius,
        showCrosshair,
        showAxisLines,
        tooltip: tooltipConfig,
        divergingStack,
        fillStyle,
        animateHover,
        legend,
        trendLines,
    } = config ?? {}
    const axisList = useMemo(() => normalizeYAxisList(yAxis), [yAxis])
    const primaryYAxis = useMemo<YAxisConfig | undefined>(() => primaryYAxisConfig(axisList), [axisList])
    const yAxes = useMemo(() => (Array.isArray(yAxis) ? buildYAxes(axisList) : undefined), [yAxis, axisList])

    const xTickFormatter = useXTickFormatter(xAxis, labels)
    const yTickFormatter = useYTickFormatter(primaryYAxis)

    const { visibleSeries, legendProps } = useChartLegend(series, theme, legend)

    const valueLabelsConfig = resolveValueLabelsConfig(valueLabels)
    const seriesAfterValueLabels = useSeriesWithValueLabelAllowlist(visibleSeries, valueLabelsConfig?.seriesKeys)

    const valueLabelFormatter = valueLabelsConfig ? (valueLabelsConfig.formatter ?? yTickFormatter) : undefined

    // `axisOrientation` flows through `barChartConfig` into chart context, so `ReferenceLine`
    // reads it automatically — no need to stamp each line here.
    const referenceLines = useMemo(
        () => buildGoalLineReferenceLines(goalLines, seriesAfterValueLabels),
        [goalLines, seriesAfterValueLabels]
    )

    // Extend the value axis to cover goal lines that sit above (or below) the data, so a goal
    // line off the data's natural scale still renders inside the plot. Memoized so the `{ include }`
    // object stays referentially stable and doesn't re-trigger scale recomputation each render.
    const valueDomain = useMemo(() => goalLineValueDomain(referenceLines), [referenceLines])

    const trendSeries = useMemo(() => {
        if (!trendLines?.length) {
            return []
        }
        const byKey = new Map(visibleSeries.map((s) => [s.key, s]))
        return trendLines.flatMap((tl) => {
            const source = byKey.get(tl.seriesKey)
            return source
                ? [buildTrendLineSeries({ sourceSeries: source, kind: tl.kind, label: tl.label, fitUpTo: tl.fitUpTo, excluded: source.visibility?.excluded })]
                : []
        })
    }, [trendLines, visibleSeries])

    const barChartConfig: BarChartConfig = {
        yScaleType: primaryYAxis?.scale,
        xTickFormatter,
        yTickFormatter,
        hideXAxis: xAxis?.hide,
        hideYAxis: primaryYAxis?.hide,
        xAxisLabel: xAxis?.label,
        yAxisLabel: primaryYAxis?.label,
        showGrid: primaryYAxis?.showGrid,
        showAxisLines,
        barLayout,
        axisOrientation,
        showCrosshair,
        tooltip: tooltipConfig,
        animateHover,
        yAxes,
        bars: {
            cornerRadius: barCornerRadius,
            divergingStack,
            valueDomain,
            fillStyle,
        },
    }

    return (
        <ChartLegend {...legendProps} legendDataAttr="hog-chart-timeseries-bar-legend">
            <BarChart
                series={seriesAfterValueLabels}
                labels={labels}
                config={barChartConfig}
                theme={theme}
                tooltip={tooltip}
                onPointClick={onPointClick}
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
