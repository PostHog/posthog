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
import { BarChart } from '../BarChart/BarChart'

export interface ValueLabelsConfig {
    seriesKeys?: string[]
    formatter?: (value: number) => string
}

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

function resolveValueLabelsConfig(valueLabels: TimeSeriesBarChartConfig['valueLabels']): ValueLabelsConfig | null {
    if (valueLabels === undefined || valueLabels === false) {
        return null
    }
    if (valueLabels === true) {
        return {}
    }
    return valueLabels
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

    // Stable primitive key so callers can pass `valueLabels: { seriesKeys: ['a'] }` inline
    // without re-running the transform on every render.
    const seriesKeysSignature = valueLabelsConfig?.seriesKeys?.join(' ')
    const seriesAfterValueLabels = useMemo(() => {
        const seriesKeys = valueLabelsConfig?.seriesKeys
        if (!seriesKeys) {
            return series
        }
        const allowed = new Set(seriesKeys)
        return series.map((s) =>
            allowed.has(s.key) ? s : { ...s, visibility: { ...s.visibility, valueLabel: false } }
        )
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [series, seriesKeysSignature])

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
