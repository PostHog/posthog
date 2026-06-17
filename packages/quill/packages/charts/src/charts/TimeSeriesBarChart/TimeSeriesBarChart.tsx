import React, { useMemo } from 'react'

import type {
    BarChartConfig,
    BarFillStyle,
    ChartTheme,
    PointClickData,
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
import { BarChart } from '../BarChart/BarChart'
import {
    resolveValueLabelsConfig,
    useSeriesWithValueLabelAllowlist,
    type ValueLabelsConfig,
} from '../utils/use-value-labels'

export interface TimeSeriesBarChartConfig {
    xAxis?: XAxisConfig
    yAxis?: YAxisConfig
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
    } = config ?? {}
    const xTickFormatter = useXTickFormatter(xAxis, labels)
    const yTickFormatter = useYTickFormatter(yAxis)

    const valueLabelsConfig = resolveValueLabelsConfig(valueLabels)
    const seriesAfterValueLabels = useSeriesWithValueLabelAllowlist(series, valueLabelsConfig?.seriesKeys)

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

    const barChartConfig: BarChartConfig = {
        yScaleType: yAxis?.scale,
        xTickFormatter,
        yTickFormatter,
        hideXAxis: xAxis?.hide,
        hideYAxis: yAxis?.hide,
        xAxisLabel: xAxis?.label,
        yAxisLabel: yAxis?.label,
        showGrid: yAxis?.showGrid,
        showAxisLines,
        barLayout,
        axisOrientation,
        showCrosshair,
        tooltip: tooltipConfig,
        animateHover,
        bars: {
            cornerRadius: barCornerRadius,
            divergingStack,
            valueDomain,
            fillStyle,
        },
    }

    return (
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
            {valueLabelsConfig && <ValueLabels valueFormatter={valueLabelFormatter} />}
            {children}
        </BarChart>
    )
}
