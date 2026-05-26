import React, { useEffect, useMemo } from 'react'

import { useChartHover } from '../../core/chart-context'
import { ChartErrorBoundary } from '../../core/ChartErrorBoundary'
import { useLatest } from '../../core/hooks/useLatest'
import type { ChartTheme, LineChartConfig, Series } from '../../core/types'
import { LineChart } from '../LineChart'

export interface SparklineProps {
    data: number[]
    /** Optional x-axis labels — when omitted, indices stand in. Consumers can look up
     *  the hovered index against their own labels. */
    labels?: string[]
    theme: ChartTheme
    color?: string
    height?: number
    /** Peak opacity of the gradient fill under the line. Range 0–1. */
    fillOpacity?: number
    /** Fires the hovered index, or -1 when not hovering. */
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
    const resolvedLabels = useMemo<string[]>(
        () => labels ?? Array.from({ length: data.length }, (_, i) => String(i)),
        [labels, data.length]
    )
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
    const wrapperStyle = useMemo<React.CSSProperties>(() => ({ height }), [height])

    return (
        <div className={`relative flex flex-col ${className ?? ''}`} style={wrapperStyle} data-attr={dataAttr}>
            <LineChart series={series} labels={resolvedLabels} theme={theme} config={SPARKLINE_CONFIG}>
                {onHoverIndexChange ? <HoverWatcher onHoverChange={onHoverIndexChange} /> : null}
            </LineChart>
        </div>
    )
}

function HoverWatcher({ onHoverChange }: { onHoverChange: (i: number) => void }): null {
    const { hoverIndex } = useChartHover()
    const cb = useLatest(onHoverChange)
    useEffect(() => {
        cb.current(hoverIndex)
    }, [hoverIndex, cb])
    // Reset to -1 on unmount so a parent still mounted after Sparkline tears down
    // doesn't keep showing the last positive hover index.
    useEffect(() => () => cb.current(-1), [cb])
    return null
}
