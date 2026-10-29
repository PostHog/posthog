/* eslint-disable react/forbid-dom-props -- fill extents and colors are dynamic values */
import React from 'react'

import { ChartErrorBoundary } from '../../core/ChartErrorBoundary'
import { useResolvedChartTheme } from '../../core/theme'
import type { ChartTheme } from '../../core/types'
import { buildYTickFormatter } from '../../utils/y-formatters'
import { gaugeArcPath, gaugeFraction, thresholdColor, thresholdSegments, type GaugeThreshold } from './gauge-geometry'

/** One gauge: a value read against the gauge's range. */
export interface GaugeItem {
    key: string
    /** Name shown under (radial, vertical bar) or beside (horizontal bar) the gauge. */
    label?: string
    /** `null` draws an empty gauge reading "No data". */
    value: number | null
    /** Fill color below every threshold. Falls back to `theme.colors` by index. */
    color?: string
}

export interface GaugeProps {
    /** One gauge per item, laid out in a grid: rows for horizontal bars, columns for vertical bars,
     *  and a wrapping grid for radial gauges. */
    items: GaugeItem[]
    /** Defaults to the nearest `ChartThemeProvider`, then the quill CSS vars. */
    theme?: ChartTheme
    /** `radial` (default) draws an arc open at the bottom; `bar` a straight bar on a track. */
    variant?: 'radial' | 'bar'
    /** Bar gauges only. Defaults to `horizontal`. */
    orientation?: 'horizontal' | 'vertical'
    /** Value at the empty end. Defaults to 0. */
    min?: number
    /** Value at the full end. Defaults to 100. */
    max?: number
    /** The fill takes the color of the highest threshold at or below the value. A radial gauge also
     *  draws each threshold's range as a band around its arc. */
    thresholds?: GaugeThreshold[]
    /** Radial gauges only: draw the threshold bands. Defaults to true when `thresholds` is set. */
    showThresholdMarkers?: boolean
    /** Formats the value text. Defaults to a locale number with significant decimals. */
    valueFormatter?: (value: number) => string
    className?: string
    dataAttr?: string
    onError?: (error: Error, info: React.ErrorInfo) => void
}

const defaultValueFormatter = buildYTickFormatter({})
const DEFAULT_TRACK_COLOR = 'rgba(0, 0, 0, 0.08)'
const NO_DATA = 'No data'

export function Gauge({ onError, ...rest }: GaugeProps): React.ReactElement {
    return (
        <ChartErrorBoundary onError={onError}>
            <GaugeInner {...rest} />
        </ChartErrorBoundary>
    )
}

interface ResolvedGauge {
    item: GaugeItem
    fraction: number
    color: string
    baseColor: string
    text: string
}

function GaugeInner({
    items,
    theme: themeProp,
    variant = 'radial',
    orientation = 'horizontal',
    min = 0,
    max = 100,
    thresholds = [],
    showThresholdMarkers = thresholds.length > 0,
    valueFormatter = defaultValueFormatter,
    className,
    dataAttr,
}: Omit<GaugeProps, 'onError'>): React.ReactElement {
    const theme = useResolvedChartTheme(themeProp)
    const track = theme.gridColor ?? DEFAULT_TRACK_COLOR
    const gauges: ResolvedGauge[] = items.map((item, i) => {
        const baseColor = item.color || theme.colors[i % theme.colors.length] || '#000'
        return {
            item,
            baseColor,
            fraction: item.value == null ? 0 : gaugeFraction(item.value, min, max),
            color: item.value == null ? baseColor : thresholdColor(item.value, thresholds, baseColor),
            text: item.value == null ? NO_DATA : valueFormatter(item.value),
        }
    })
    const meter = (g: ResolvedGauge): React.HTMLAttributes<HTMLDivElement> => ({
        role: 'meter',
        'aria-label': g.item.label,
        'aria-valuemin': min,
        'aria-valuemax': max,
        'aria-valuenow': g.item.value ?? undefined,
        'aria-valuetext': g.text,
    })
    const label = (g: ResolvedGauge, extra = ''): React.ReactNode =>
        g.item.label ? (
            <div
                className={`truncate min-w-0 text-xs text-(--color-graph-axis-label) ${extra}`}
                title={g.item.label}
                data-attr="hog-chart-gauge-label"
            >
                {g.item.label}
            </div>
        ) : null
    const value = (g: ResolvedGauge, extra = '', width?: string): React.ReactNode => (
        <div
            className={`font-semibold tabular-nums whitespace-nowrap ${extra}`}
            style={{ color: g.item.value == null ? undefined : g.color, width }}
            data-attr="hog-chart-gauge-value"
        >
            {g.text}
        </div>
    )

    if (variant === 'bar' && orientation === 'vertical') {
        return (
            <div className={`flex h-full w-full gap-3 ${className ?? ''}`} data-attr={dataAttr}>
                {gauges.map((g) => (
                    <div key={g.item.key} className="flex flex-col flex-1 min-w-0 items-center gap-1" {...meter(g)}>
                        {value(g, 'text-sm')}
                        <div className="relative flex-1 w-full max-w-10 rounded" style={{ backgroundColor: track }}>
                            <div
                                className="absolute bottom-0 inset-x-0 rounded"
                                style={{ height: `${g.fraction * 100}%`, backgroundColor: g.color }}
                                data-attr="hog-chart-gauge-fill"
                            />
                        </div>
                        {label(g, 'w-full text-center')}
                    </div>
                ))}
            </div>
        )
    }

    if (variant === 'bar') {
        // One value column width for every row, so the tracks line up.
        const valueWidth = `${Math.max(...gauges.map((g) => g.text.length))}ch`
        return (
            <div className={`flex flex-col justify-center w-full gap-2 ${className ?? ''}`} data-attr={dataAttr}>
                {gauges.map((g) => (
                    <div key={g.item.key} className="flex items-center gap-2 min-w-0" {...meter(g)}>
                        {label(g, 'w-1/3 shrink-0')}
                        <div className="relative flex-1 h-4 min-w-0 rounded" style={{ backgroundColor: track }}>
                            <div
                                className="absolute inset-y-0 left-0 rounded"
                                style={{ width: `${g.fraction * 100}%`, backgroundColor: g.color }}
                                data-attr="hog-chart-gauge-fill"
                            />
                        </div>
                        {value(g, 'text-sm text-right shrink-0', valueWidth)}
                    </div>
                ))}
            </div>
        )
    }

    return (
        <div
            className={`grid h-full w-full gap-3 grid-cols-[repeat(auto-fit,minmax(7rem,1fr))] content-center ${className ?? ''}`}
            data-attr={dataAttr}
        >
            {gauges.map((g) => (
                <div key={g.item.key} className="flex flex-col items-center min-w-0 min-h-0" {...meter(g)}>
                    <svg viewBox="0 0 200 160" className="w-full max-h-full" aria-hidden="true">
                        {showThresholdMarkers &&
                            thresholdSegments(thresholds, min, max, g.baseColor).map((segment) => (
                                <path
                                    key={`${segment.from}-${segment.color}`}
                                    d={gaugeArcPath(100, 100, 90, segment.from, segment.to)}
                                    fill="none"
                                    stroke={segment.color}
                                    strokeWidth={4}
                                />
                            ))}
                        <path d={gaugeArcPath(100, 100, 74, 0, 1)} fill="none" stroke={track} strokeWidth={18} />
                        {g.fraction > 0 && (
                            <path
                                d={gaugeArcPath(100, 100, 74, 0, g.fraction)}
                                fill="none"
                                stroke={g.color}
                                strokeWidth={18}
                                data-attr="hog-chart-gauge-fill"
                            />
                        )}
                        <text
                            x={100}
                            y={110}
                            textAnchor="middle"
                            // Shrink long values so they stay inside the arc.
                            fontSize={Math.min(g.item.value == null ? 20 : 32, 260 / Math.max(g.text.length, 1))}
                            fontWeight={600}
                            fill={g.item.value == null ? 'currentColor' : g.color}
                            className="tabular-nums"
                            data-attr="hog-chart-gauge-value"
                        >
                            {g.text}
                        </text>
                    </svg>
                    {label(g, 'w-full text-center -mt-4')}
                </div>
            ))}
        </div>
    )
}
