import React, { useMemo } from 'react'

import type {
    BarChartConfig,
    ChartTheme,
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
import { BarChart } from '../BarChart/BarChart'

export type { ValueLabelsConfig }

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
    /** Tooltip behaviour (pinning, placement). Tooltip *content* is the `tooltip` render prop. */
    tooltip?: TooltipConfig
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
        tooltip: tooltipConfig,
    } = config ?? {}
    const xTickFormatter = useXTickFormatter(xAxis, labels)
    const yTickFormatter = useYTickFormatter(yAxis)

    const valueLabelsConfig = resolveValueLabelsConfig(valueLabels)
    const seriesAfterValueLabels = useSeriesWithValueLabelAllowlist(series, valueLabelsConfig?.seriesKeys)

    const valueLabelFormatter = valueLabelsConfig ? (valueLabelsConfig.formatter ?? yTickFormatter) : undefined

    const referenceLines = useMemo(
        () => buildGoalLineReferenceLines(goalLines, seriesAfterValueLabels),
        [goalLines, seriesAfterValueLabels]
    )

    const orientedReferenceLines = useMemo(
        () =>
            axisOrientation === 'horizontal'
                ? referenceLines.map((line) => ({ ...line, axisOrientation: 'horizontal' as const }))
                : referenceLines,
        [referenceLines, axisOrientation]
    )

    const barChartConfig: BarChartConfig = {
        yScaleType: yAxis?.scale,
        xTickFormatter,
        yTickFormatter,
        hideXAxis: xAxis?.hide,
        hideYAxis: yAxis?.hide,
        showGrid: yAxis?.showGrid,
        barLayout,
        barCornerRadius,
        axisOrientation,
        showCrosshair,
        tooltip: tooltipConfig,
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
            {orientedReferenceLines.length > 0 && <ReferenceLines lines={orientedReferenceLines} />}
            {valueLabelsConfig && <ValueLabels valueFormatter={valueLabelFormatter} />}
            {children}
        </BarChart>
    )
}
