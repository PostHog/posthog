import React, { useMemo } from 'react'

import type { ChartTheme, LineChartConfig, PointClickData, Series, TooltipContext } from '../../core/types'
import { ReferenceLines } from '../../overlays/ReferenceLine'
import { LineChart } from '../LineChart'
import { buildGoalLineReferenceLines, type GoalLineConfig } from './utils/goal-lines'
import { useXTickFormatter, useYTickFormatter, type XAxisConfig, type YAxisConfig } from './utils/use-axis-formatters'

export interface TimeSeriesLineChartConfig {
    xAxis?: XAxisConfig
    yAxis?: YAxisConfig
    goalLines?: GoalLineConfig[]
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
    const { xAxis, yAxis, goalLines } = config ?? {}
    const xTickFormatter = useXTickFormatter(xAxis, labels)
    const yTickFormatter = useYTickFormatter(yAxis)

    const referenceLines = useMemo(() => buildGoalLineReferenceLines(goalLines, series), [goalLines, series])

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
            series={series}
            labels={labels}
            config={lineChartConfig}
            theme={theme}
            tooltip={tooltip}
            onPointClick={onPointClick}
            className={className}
            dataAttr={dataAttr}
        >
            {referenceLines.length > 0 && <ReferenceLines lines={referenceLines} />}
            {children}
        </LineChart>
    )
}
