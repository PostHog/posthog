import React, { useMemo } from 'react'

import type {
    ChartTheme,
    LineChartConfig,
    PointClickData,
    Series,
    TooltipConfig,
    TooltipContext,
} from '../../core/types'
import { ReferenceLines } from '../../overlays/ReferenceLine'
import { ValueLabels } from '../../overlays/ValueLabels'
import { buildGoalLineReferenceLines, type GoalLineConfig } from '../../utils/goal-lines'
import {
    useXTickFormatter,
    useYTickFormatter,
    type XAxisConfig,
    type YAxisConfig,
} from '../../utils/use-axis-formatters'
import {
    resolveValueLabelsConfig,
    useSeriesWithValueLabelAllowlist,
    type ValueLabelsConfig,
} from '../utils/use-value-labels'
import { LineChart } from '../LineChart'
import {
    useDerivedSeries,
    type ConfidenceIntervalConfig,
    type MovingAverageConfig,
    type TrendLineConfig,
} from './utils/use-derived-series'

export type { ValueLabelsConfig }
export type { ConfidenceIntervalConfig, MovingAverageConfig, TrendLineConfig }

export interface TimeSeriesLineChartConfig {
    xAxis?: XAxisConfig
    yAxis?: YAxisConfig
    valueLabels?: boolean | ValueLabelsConfig
    goalLines?: GoalLineConfig[]
    confidenceIntervals?: ConfidenceIntervalConfig[]
    movingAverage?: MovingAverageConfig[]
    trendLines?: TrendLineConfig[]
    /** Comparison series keys mapped to their primary. Comparison series render dimmed. */
    comparisonOf?: Record<string, string>
    /** Render area-fill series as a 100% stacked view; y-axis becomes 0–100%. */
    percentStackView?: boolean
    /** Show a vertical crosshair line that follows the cursor. */
    showCrosshair?: boolean
    /** Tooltip behaviour (pinning, placement). Tooltip *content* is the `tooltip` render prop. */
    tooltip?: TooltipConfig
}

export interface TimeSeriesLineChartProps<Meta = unknown> {
    series: Series<Meta>[]
    labels: string[]
    theme: ChartTheme
    config?: TimeSeriesLineChartConfig
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    onPointClick?: (data: PointClickData<Meta>) => void
    dataAttr?: string
    className?: string
    children?: React.ReactNode
    onError?: (error: Error, info: React.ErrorInfo) => void
}

export function TimeSeriesLineChart<Meta = unknown>({
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
}: TimeSeriesLineChartProps<Meta>): React.ReactElement {
    const {
        xAxis,
        yAxis,
        valueLabels,
        goalLines,
        confidenceIntervals,
        movingAverage,
        trendLines,
        comparisonOf,
        percentStackView,
        showCrosshair,
        tooltip: tooltipConfig,
    } = config ?? {}
    const xTickFormatter = useXTickFormatter(xAxis, labels)
    const yTickFormatter = useYTickFormatter(yAxis)

    const valueLabelsConfig = resolveValueLabelsConfig(valueLabels)
    const seriesAfterValueLabels = useSeriesWithValueLabelAllowlist(series, valueLabelsConfig?.seriesKeys)

    const finalSeries = useDerivedSeries(seriesAfterValueLabels, {
        confidenceIntervals,
        movingAverage,
        trendLines,
        comparisonOf,
    })

    const valueLabelFormatter = valueLabelsConfig ? (valueLabelsConfig.formatter ?? yTickFormatter) : undefined

    const referenceLines = useMemo(() => buildGoalLineReferenceLines(goalLines, finalSeries), [goalLines, finalSeries])

    const lineChartConfig: LineChartConfig = {
        yScaleType: yAxis?.scale,
        xTickFormatter,
        yTickFormatter,
        hideXAxis: xAxis?.hide,
        hideYAxis: yAxis?.hide,
        showGrid: yAxis?.showGrid,
        percentStackView,
        showCrosshair,
        tooltip: tooltipConfig,
    }

    return (
        <LineChart
            series={finalSeries}
            labels={labels}
            config={lineChartConfig}
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
        </LineChart>
    )
}
