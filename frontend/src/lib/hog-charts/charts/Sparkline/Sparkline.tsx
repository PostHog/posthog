import React, { useEffect, useMemo } from 'react'

import { useChartHover } from '../../core/chart-context'
import { ChartErrorBoundary } from '../../core/ChartErrorBoundary'
import type { ChartTheme, LineChartConfig, Series } from '../../core/types'
import { LineChart } from '../LineChart'

export interface SparklineProps {
    /** Series values. */
    data: number[]
    /** Optional x-axis labels — when omitted, indices stand in. Sparkline never renders
     *  them itself, but downstream consumers can read the hovered index and look the
     *  label up. */
    labels?: string[]
    theme: ChartTheme
    /** Line + fill color. Falls back to `theme.colors[0]`. */
    color?: string
    /** Height of the chart area in CSS pixels. Defaults to 120. */
    height?: number
    /** Peak opacity of the gradient fill under the line (0–1). Defaults to 0.35. */
    fillOpacity?: number
    /** Fires the hovered index, or -1 when not hovering. Consumers use this to drive
     *  a hover-following headline; Sparkline itself owns the chart-context subscription
     *  so callers never need to touch `useChartHover`. */
    onHoverIndexChange?: (index: number) => void
    className?: string
    dataAttr?: string
    onError?: (error: Error, info: React.ErrorInfo) => void
}

const SPARKLINE_CONFIG: LineChartConfig = {
    hideXAxis: true,
    hideYAxis: true,
    showCrosshair: true,
    tooltip: { enabled: false },
    margins: { top: 0, right: 0, bottom: 0, left: 0 },
}

export function Sparkline(props: SparklineProps): React.ReactElement {
    const { onError, ...rest } = props
    return (
        <ChartErrorBoundary onError={onError}>
            <SparklineInner {...rest} />
        </ChartErrorBoundary>
    )
}

function SparklineInner({
    data,
    labels,
    theme,
    color,
    height = 120,
    fillOpacity = 0.35,
    onHoverIndexChange,
    className,
    dataAttr,
}: Omit<SparklineProps, 'onError'>): React.ReactElement {
    const resolvedColor = color ?? theme.colors[0]
    const resolvedLabels = useMemo<string[]>(() => labels ?? data.map((_, i) => String(i)), [labels, data])
    const series = useMemo<Series[]>(
        () => [
            {
                key: 'sparkline',
                label: 'sparkline',
                data,
                color: resolvedColor,
                fill: { gradient: true, opacity: fillOpacity },
            },
        ],
        [data, resolvedColor, fillOpacity]
    )

    return (
        <div className={`relative flex flex-col ${className ?? ''}`} style={{ height }} data-attr={dataAttr}>
            <LineChart series={series} labels={resolvedLabels} theme={theme} config={SPARKLINE_CONFIG}>
                {onHoverIndexChange ? <HoverWatcher onHoverChange={onHoverIndexChange} /> : null}
            </LineChart>
        </div>
    )
}

function HoverWatcher({ onHoverChange }: { onHoverChange: (i: number) => void }): null {
    const { hoverIndex } = useChartHover()
    useEffect(() => {
        onHoverChange(hoverIndex)
    }, [hoverIndex, onHoverChange])
    return null
}
