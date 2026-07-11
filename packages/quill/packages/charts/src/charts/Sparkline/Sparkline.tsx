import React, { useEffect, useMemo } from 'react'

import { useChartHover } from '../../core/chart-context'
import { ChartErrorBoundary } from '../../core/ChartErrorBoundary'
import { useLatest } from '../../core/hooks/useLatest'
import type { BarChartConfig, ChartTheme, LineChartConfig, Series, TooltipContext } from '../../core/types'
import { BarChart } from '../BarChart/BarChart'
import { LineChart } from '../LineChart/LineChart'

export interface SparklineProps {
    /** Single-series values. Ignored when `series` is provided. */
    data?: number[]
    /** Multi-series form with full per-series control (color, fill, stroke). Bars render stacked.
     *  When set, the single-series conveniences (`data`, `color`, `fillOpacity`,
     *  `dashedFromIndex`) are ignored — express them on the series entries instead. */
    series?: Series[]
    /** Optional x-axis labels — when omitted, indices stand in. Consumers can look up
     *  the hovered index against their own labels. */
    labels?: string[]
    theme: ChartTheme
    color?: string
    /** `line` (default) draws a gradient-filled trend line; `bar` draws stacked bars. */
    type?: 'line' | 'bar'
    height?: number
    /** Fill the parent's height (flex child) instead of using a fixed `height`. */
    fill?: boolean
    /** Peak opacity of the gradient fill under the line. Range 0–1. */
    fillOpacity?: number
    /** Dash the line from this index onward (e.g. an in-progress trailing period). Omit for a fully solid line. */
    dashedFromIndex?: number
    /** Fires the hovered index, or -1 when not hovering. */
    onHoverIndexChange?: (index: number) => void
    /** Tooltip content renderer. Sparkline tooltips are off by default; supplying this enables them. */
    tooltip?: (ctx: TooltipContext) => React.ReactNode
    className?: string
    dataAttr?: string
    onError?: (error: Error, info: React.ErrorInfo) => void
}

const BASE_CONFIG = { hideXAxis: true, hideYAxis: true } as const
// Reserve room for the hover highlight ring (radius + 2 = 6px) so it isn't clipped at the top/bottom edge.
const LINE_MARGINS = { top: 6, right: 0, bottom: 6, left: 0 }
// Bars have no hover ring — sit them flush on the baseline, with a sliver of headroom for the tallest stack.
const BAR_MARGINS = { top: 2, right: 0, bottom: 0, left: 0 }

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
    series,
    labels,
    theme,
    color,
    type = 'line',
    height = 120,
    fill = false,
    fillOpacity = 0.35,
    dashedFromIndex,
    onHoverIndexChange,
    tooltip,
    className,
    dataAttr,
}: Omit<SparklineProps, 'onError'>): React.ReactElement {
    const resolvedColor = color ?? theme.colors[0]
    const chartSeries = useMemo<Series[]>(() => {
        if (series) {
            return series
        }
        const single: Series = { key: 'sparkline', label: 'sparkline', data: data ?? [], color: resolvedColor }
        if (type === 'line') {
            single.fill = { gradient: true, opacity: fillOpacity }
            if (dashedFromIndex != null) {
                single.stroke = { partial: { fromIndex: dashedFromIndex } }
            }
        }
        return [single]
    }, [series, data, resolvedColor, type, fillOpacity, dashedFromIndex])
    const pointCount = chartSeries[0]?.data.length ?? 0
    const resolvedLabels = useMemo<string[]>(
        () => labels ?? Array.from({ length: pointCount }, (_, i) => String(i)),
        [labels, pointCount]
    )
    const hasTooltip = tooltip != null
    const config = useMemo<LineChartConfig & BarChartConfig>(
        () => ({
            ...BASE_CONFIG,
            ...(type === 'bar'
                ? { barCornerRadius: 2, margins: BAR_MARGINS }
                : { showCrosshair: true, margins: LINE_MARGINS }),
            ...(hasTooltip ? {} : { tooltip: { enabled: false } }),
        }),
        [type, hasTooltip]
    )
    const wrapperStyle = useMemo<React.CSSProperties | undefined>(() => (fill ? undefined : { height }), [fill, height])

    const watcher = onHoverIndexChange ? <HoverWatcher onHoverChange={onHoverIndexChange} /> : null
    return (
        <div
            className={`relative flex flex-col ${fill ? 'flex-1 min-h-0' : ''} ${className ?? ''}`}
            style={wrapperStyle}
            data-attr={dataAttr}
        >
            {type === 'bar' ? (
                <BarChart series={chartSeries} labels={resolvedLabels} theme={theme} config={config} tooltip={tooltip}>
                    {watcher}
                </BarChart>
            ) : (
                <LineChart series={chartSeries} labels={resolvedLabels} theme={theme} config={config} tooltip={tooltip}>
                    {watcher}
                </LineChart>
            )}
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
