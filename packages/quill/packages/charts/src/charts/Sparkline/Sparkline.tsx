import React, { useEffect, useMemo } from 'react'

import { useChartHover } from '../../core/chart-context'
import { ChartErrorBoundary } from '../../core/ChartErrorBoundary'
import { useLatest } from '../../core/hooks/useLatest'
import { seriesValueRange } from '../../core/scales'
import type { ChartTheme, LineChartConfig, Series } from '../../core/types'
import { LineChart } from '../LineChart/LineChart'

export interface SparklineProps {
    data: number[]
    /** Optional x-axis labels — when omitted, indices stand in. Consumers can look up
     *  the hovered index against their own labels. */
    labels?: string[]
    theme: ChartTheme
    color?: string
    height?: number
    /** Fill the parent's height (flex child) instead of using a fixed `height`. */
    fill?: boolean
    /** Peak opacity of the gradient fill under the line. Range 0–1. */
    fillOpacity?: number
    /** Dash the line from this index onward (e.g. an in-progress trailing period). Omit for a fully solid line. */
    dashedFromIndex?: number
    /** Fires the hovered index, or -1 when not hovering. */
    onHoverIndexChange?: (index: number) => void
    className?: string
    dataAttr?: string
    onError?: (error: Error, info: React.ErrorInfo) => void
}

/** Hug the data range: a fixed domain (no tick-nicing) puts the lowest point on the plot bottom
 *  instead of floating mid-plot. A flat series reads against a zero baseline instead — flat 0 runs
 *  along the bottom, a flat non-zero value along the top — so a steady value doesn't read as zero.
 *  `undefined` (no finite values) falls back to the scale's own domain. */
export function sparklineValueDomain(data: number[]): [number, number] | undefined {
    const { min, max, count } = seriesValueRange([{ key: 'sparkline', label: 'sparkline', data }])
    if (count === 0) {
        return undefined
    }
    if (max !== min) {
        return [min, max]
    }
    if (max === 0) {
        return [0, 1]
    }
    return max > 0 ? [0, max] : [max, 0]
}

const SPARKLINE_CONFIG: LineChartConfig = {
    hideXAxis: true,
    hideYAxis: true,
    showCrosshair: true,
    tooltip: { enabled: false },
    // Reserve room for the hover highlight ring (radius + 2 = 6px) so it isn't clipped at the top/bottom edge.
    margins: { top: 6, right: 0, bottom: 6, left: 0 },
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
    fill = false,
    fillOpacity = 0.35,
    dashedFromIndex,
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
                stroke: dashedFromIndex != null ? { partial: { fromIndex: dashedFromIndex } } : undefined,
            },
        ],
        [data, resolvedColor, fillOpacity, dashedFromIndex]
    )
    const config = useMemo<LineChartConfig>(() => {
        const valueDomain = sparklineValueDomain(data)
        return valueDomain ? { ...SPARKLINE_CONFIG, valueDomain } : SPARKLINE_CONFIG
    }, [data])
    const wrapperStyle = useMemo<React.CSSProperties | undefined>(() => (fill ? undefined : { height }), [fill, height])

    return (
        <div
            className={`relative flex flex-col ${fill ? 'flex-1 min-h-0' : ''} ${className ?? ''}`}
            style={wrapperStyle}
            data-attr={dataAttr}
        >
            <LineChart series={series} labels={resolvedLabels} theme={theme} config={config}>
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
