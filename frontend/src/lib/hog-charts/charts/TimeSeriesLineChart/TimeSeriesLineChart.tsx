import React, { useMemo } from 'react'

import type { ChartTheme, LineChartConfig, PointClickData, Series, TooltipContext } from '../../core/types'
import { ReferenceLines } from '../../overlays/ReferenceLine'
import { ValueLabels } from '../../overlays/ValueLabels'
import { LineChart } from '../LineChart'
import { buildGoalLineReferenceLines, type GoalLineConfig } from './utils/goal-lines'
import { useXTickFormatter, useYTickFormatter, type XAxisConfig, type YAxisConfig } from './utils/use-axis-formatters'
import { buildYTickFormatter } from './utils/y-formatters'

export interface ValueLabelsConfig {
    /** When set, only series whose `key` is in this list get value labels.
     *  Other series stay rendered on the chart but skip the labels overlay. */
    seriesKeys?: string[]
    /** Override the label text formatter. Falls back to a `yAxis`-driven
     *  formatter when omitted (or no formatter when `yAxis.format` is unset). */
    formatter?: (value: number) => string
}

export interface InProgressConfig {
    /** Index from which the in-progress (dashed) tail begins. Series whose
     *  `stroke.partial` is already set keep their explicit value. */
    fromIndex: number
}

export interface TimeSeriesLineChartConfig {
    xAxis?: XAxisConfig
    yAxis?: YAxisConfig
    /** Mark the tail of every series as in-progress (dashed). */
    inProgress?: InProgressConfig
    /** Render the {@link ValueLabels} overlay. `true` enables it with defaults;
     *  passing an object configures filtering/formatting. */
    valueLabels?: boolean | ValueLabelsConfig
    /** Render goal lines as horizontal {@link ReferenceLines} on the chart. */
    goalLines?: GoalLineConfig[]
}

export interface TimeSeriesLineChartProps<Meta = unknown> {
    series: Series<Meta>[]
    /** Pre-formatted time labels. Length must match each series.data. */
    labels: string[]
    theme: ChartTheme
    config?: TimeSeriesLineChartConfig
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    onPointClick?: (data: PointClickData<Meta>) => void
    /** `data-attr` applied to the chart wrapper for product-level test selectors. */
    dataAttr?: string
    className?: string
    /** Custom overlays composed alongside the built-in ones (rendered after them). */
    children?: React.ReactNode
}

function resolveValueLabelsConfig(valueLabels: TimeSeriesLineChartConfig['valueLabels']): ValueLabelsConfig | null {
    if (valueLabels === undefined || valueLabels === false) {
        return null
    }
    if (valueLabels === true) {
        return {}
    }
    return valueLabels
}

function hasYFormatterConfig(yAxis: YAxisConfig | undefined): boolean {
    if (!yAxis) {
        return false
    }
    return (
        yAxis.format !== undefined ||
        yAxis.prefix !== undefined ||
        yAxis.suffix !== undefined ||
        yAxis.decimalPlaces !== undefined ||
        yAxis.minDecimalPlaces !== undefined ||
        yAxis.currency !== undefined
    )
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
}: TimeSeriesLineChartProps<Meta>): React.ReactElement {
    const { xAxis, yAxis, inProgress, valueLabels, goalLines } = config ?? {}
    const xTickFormatter = useXTickFormatter(xAxis, labels)
    const yTickFormatter = useYTickFormatter(yAxis)

    const valueLabelsConfig = resolveValueLabelsConfig(valueLabels)

    const seriesWithInProgress = useMemo(() => {
        if (inProgress?.fromIndex === undefined) {
            return series
        }
        const fromIndex = inProgress.fromIndex
        return series.map((s) =>
            s.stroke?.partial !== undefined ? s : { ...s, stroke: { ...s.stroke, partial: { fromIndex } } }
        )
    }, [series, inProgress?.fromIndex])

    // Filter ValueLabels overlay via the per-series `fromValueLabels` flag — leaves
    // everything else (rendering, hit-testing, tooltips) untouched.
    const transformedSeries = useMemo(() => {
        const seriesKeys = valueLabelsConfig?.seriesKeys
        if (!seriesKeys) {
            return seriesWithInProgress
        }
        const allowed = new Set(seriesKeys)
        return seriesWithInProgress.map((s) =>
            allowed.has(s.key) ? s : { ...s, visibility: { ...s.visibility, fromValueLabels: true } }
        )
    }, [seriesWithInProgress, valueLabelsConfig?.seriesKeys])

    const valueLabelFormatter = useMemo(() => {
        if (!valueLabelsConfig) {
            return undefined
        }
        if (valueLabelsConfig.formatter) {
            return valueLabelsConfig.formatter
        }
        if (hasYFormatterConfig(yAxis)) {
            return buildYTickFormatter({
                format: yAxis?.format,
                prefix: yAxis?.prefix,
                suffix: yAxis?.suffix,
                decimalPlaces: yAxis?.decimalPlaces,
                minDecimalPlaces: yAxis?.minDecimalPlaces,
                currency: yAxis?.currency,
            })
        }
        return undefined
    }, [valueLabelsConfig, yAxis])

    const referenceLines = useMemo(
        () => buildGoalLineReferenceLines(goalLines, transformedSeries),
        [goalLines, transformedSeries]
    )

    const lineChartConfig: LineChartConfig = {
        yScaleType: yAxis?.scale,
        xTickFormatter,
        yTickFormatter,
        hideXAxis: xAxis?.hide,
        hideYAxis: yAxis?.hide,
        showGrid: yAxis?.showGrid,
    }

    return (
        <LineChart
            series={transformedSeries}
            labels={labels}
            config={lineChartConfig}
            theme={theme}
            tooltip={tooltip}
            onPointClick={onPointClick}
            className={className}
            dataAttr={dataAttr}
        >
            {referenceLines.length > 0 && <ReferenceLines lines={referenceLines} />}
            {valueLabelsConfig && (
                <ValueLabels valueFormatter={valueLabelFormatter ? (v) => valueLabelFormatter(v) : undefined} />
            )}
            {children}
        </LineChart>
    )
}
