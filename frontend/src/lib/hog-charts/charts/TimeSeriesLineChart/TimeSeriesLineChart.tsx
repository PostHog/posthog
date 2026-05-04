import React, { useMemo } from 'react'

import type { ChartTheme, LineChartConfig, PointClickData, Series, TooltipContext } from '../../core/types'
import { ReferenceLines } from '../../overlays/ReferenceLine'
import { ValueLabels } from '../../overlays/ValueLabels'
import { LineChart } from '../LineChart'
import { AnomalyPointsLayer, type AnomalyMarker } from './overlays/AnomalyPointsLayer'
import { buildGoalLineReferenceLines, type GoalLineConfig } from './utils/goal-lines'
import { applyInProgressToSeries, type InProgressConfig } from './utils/in-progress'
import { useXTickFormatter, useYTickFormatter, type XAxisConfig, type YAxisConfig } from './utils/use-axis-formatters'

export interface ValueLabelsConfig {
    seriesKeys?: string[]
    formatter?: (value: number) => string
}

export interface TimeSeriesLineChartConfig {
    xAxis?: XAxisConfig
    yAxis?: YAxisConfig
    inProgress?: InProgressConfig
    valueLabels?: boolean | ValueLabelsConfig
    goalLines?: GoalLineConfig[]
    /** Anomaly markers rendered as filled circles on top of the chart. */
    anomalies?: AnomalyMarker[]
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
    const { xAxis, yAxis, inProgress, valueLabels, goalLines, anomalies } = config ?? {}
    const xTickFormatter = useXTickFormatter(xAxis, labels)
    const yTickFormatter = useYTickFormatter(yAxis)

    const valueLabelsConfig = resolveValueLabelsConfig(valueLabels)

    const seriesWithInProgress = useMemo(
        () => applyInProgressToSeries(series, inProgress),
        [series, inProgress?.fromIndex]
    )

    // Stable primitive key so callers can pass `valueLabels: { seriesKeys: ['a'] }` inline
    // without re-running the transform on every render.
    const seriesKeysSignature = valueLabelsConfig?.seriesKeys?.join(' ')
    const transformedSeries = useMemo(() => {
        const seriesKeys = valueLabelsConfig?.seriesKeys
        if (!seriesKeys) {
            return seriesWithInProgress
        }
        const allowed = new Set(seriesKeys)
        return seriesWithInProgress.map((s) =>
            allowed.has(s.key) ? s : { ...s, visibility: { ...s.visibility, fromValueLabels: true } }
        )
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [seriesWithInProgress, seriesKeysSignature])

    const valueLabelFormatter = valueLabelsConfig ? (valueLabelsConfig.formatter ?? yTickFormatter) : undefined

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
            {valueLabelsConfig && <ValueLabels valueFormatter={valueLabelFormatter} />}
            {anomalies && anomalies.length > 0 && <AnomalyPointsLayer markers={anomalies} />}
            {children}
        </LineChart>
    )
}
