import React, { useMemo, useState } from 'react'

import { Sparkline } from '../../charts/Sparkline/Sparkline'
import { ChartErrorBoundary } from '../../core/ChartErrorBoundary'
import type { ChartTheme } from '../../core/types'
import { percentage } from '../../utils/format'
import { type MetricChange, resolveDelta } from './resolveDelta'
import { useAnimatedNumber } from './useAnimatedNumber'
import { useHoverIntent } from './useHoverIntent'

export type { MetricChange }

export interface ChangeColor {
    background: string
    foreground: string
}

export interface MetricCardProps {
    title: React.ReactNode
    /** Resting headline number. Defaults to `data[data.length - 1]` when `data` is present;
     *  required when `data` is empty or omitted. */
    value?: number
    /** Series values. When present, a sparkline renders below the headline and hovering a point
     *  swaps the headline. */
    data?: number[]
    /** Labels paired with `data`. Used for the default subtitle on hover. */
    labels?: string[]
    /** Required when `data` is present. */
    theme?: ChartTheme
    /** Sparkline line + fill color. Falls back to `theme.colors[0]`. */
    color?: string
    sparklineHeight?: number
    /** Fill the card's remaining height with the sparkline instead of using a fixed `sparklineHeight`. */
    sparklineFill?: boolean
    sparklineFillOpacity?: number
    sparklineClassName?: string
    formatValue?: (value: number) => string
    formatChange?: (percent: number) => string
    showChange?: boolean
    /** Fixed comparison pill. Supplied → no hover-driven fallback. Pass `null` to suppress. */
    change?: MetricChange | null
    goodDirection?: 'up' | 'down'
    /** Size of the change pill. Defaults to `sm`. */
    changeSize?: 'sm' | 'md'
    /** Render the change pill inline next to the headline instead of in the header row. */
    changeInline?: boolean
    positiveColor?: ChangeColor
    negativeColor?: ChangeColor
    /** Caption under the headline. Defaults to `labels[activeIndex]` when a sparkline is present. */
    subtitle?: React.ReactNode
    /** Override the headline rendering. Receives the already-formatted value string (the hover-animated
     *  value when a sparkline is present); return the node to render in place of the default headline —
     *  e.g. to attach click handlers or custom typography. */
    headline?: (formattedValue: string) => React.ReactNode
    animationMs?: number
    /** Dwell (ms) a pointer must settle on the sparkline before the headline follows it.
     *  Keeps a quick pass-through from grabbing attention. `0` disables the gating. */
    hoverIntentMs?: number
    className?: string
    dataAttr?: string
    onError?: (error: Error, info: React.ErrorInfo) => void
}

const DEFAULT_POSITIVE_COLOR: ChangeColor = { background: 'rgb(56 134 0 / 10%)', foreground: '#388600' }
const DEFAULT_NEGATIVE_COLOR: ChangeColor = { background: 'rgb(219 55 7 / 10%)', foreground: '#db3707' }

const DEFAULT_FORMAT_VALUE = (v: number): string => v.toLocaleString()
const DEFAULT_FORMAT_CHANGE = (p: number): string => {
    const formatted = percentage(p / 100, 1, true)
    return p > 0 ? `+${formatted}` : formatted
}

export function MetricCard(props: MetricCardProps): React.ReactElement | null {
    const { onError, ...rest } = props
    return (
        <ChartErrorBoundary onError={onError}>
            <MetricCardInner {...rest} />
        </ChartErrorBoundary>
    )
}

function MetricCardInner({
    title,
    value,
    data,
    labels,
    theme,
    color,
    sparklineHeight = 120,
    sparklineFill = false,
    sparklineFillOpacity = 0.35,
    sparklineClassName = 'mt-4',
    formatValue = DEFAULT_FORMAT_VALUE,
    formatChange = DEFAULT_FORMAT_CHANGE,
    showChange = true,
    change,
    goodDirection = 'up',
    changeSize = 'sm',
    changeInline = false,
    positiveColor = DEFAULT_POSITIVE_COLOR,
    negativeColor = DEFAULT_NEGATIVE_COLOR,
    subtitle,
    headline,
    animationMs = 350,
    hoverIntentMs = 140,
    className,
    dataAttr,
}: Omit<MetricCardProps, 'onError'>): React.ReactElement | null {
    const sparklineData = data != null && data.length > 0 && theme != null ? data : null
    const lastIndex = sparklineData ? sparklineData.length - 1 : -1

    const [hoverIndex, setHoverIndex] = useState(-1)
    const intentIndex = useHoverIntent(hoverIndex, hoverIntentMs)
    const activeIndex = intentIndex >= 0 ? intentIndex : lastIndex

    const restingValue = value ?? (sparklineData ? sparklineData[lastIndex] : undefined)
    const animationTarget = sparklineData && intentIndex >= 0 ? (sparklineData[intentIndex] ?? 0) : (restingValue ?? 0)
    const animatedValue = useAnimatedNumber(animationTarget, animationMs)

    const baselineValue = useMemo(() => sparklineData?.find((v) => v !== 0 && Number.isFinite(v)), [sparklineData])

    if (restingValue == null) {
        return null
    }

    const liveValue = sparklineData ? (sparklineData[activeIndex] ?? 0) : restingValue
    const fallbackChangePercent =
        sparklineData == null || baselineValue == null
            ? null
            : ((liveValue - baselineValue) / Math.abs(baselineValue)) * 100

    const delta = resolveDelta({ showChange, change, fallbackChangePercent, formatChange })
    const headlineDisplay = sparklineData ? formatValue(animatedValue) : formatValue(restingValue)
    const resolvedSubtitle = subtitle ?? labels?.[activeIndex]

    const positive = delta != null && delta.value >= 0
    const isGood = goodDirection === 'up' ? positive : !positive
    const pillColors = isGood ? positiveColor : negativeColor

    const headerDelta = delta != null && !changeInline ? delta : null
    const showHeader = title != null || headerDelta != null
    // With a title, space it against the pill; with only a pill (no title), keep the pill on the right.
    const headerJustify = title != null ? 'justify-between' : 'justify-end'
    const renderedHeadline = headline ? (
        headline(headlineDisplay)
    ) : (
        <div className="mt-2 text-4xl font-bold tracking-tight tabular-nums">{headlineDisplay}</div>
    )

    return (
        <div className={`flex flex-col w-full ${className ?? ''}`} data-attr={dataAttr}>
            {showHeader && (
                <div className={`flex items-start gap-2 ${headerJustify}`}>
                    {title != null && <div className="text-sm font-medium">{title}</div>}
                    {headerDelta != null && (
                        <ChangePill positive={positive} label={headerDelta.label} colors={pillColors} size={changeSize} />
                    )}
                </div>
            )}

            {changeInline && delta != null ? (
                <div className="flex items-center justify-between gap-2">
                    {renderedHeadline}
                    <ChangePill positive={positive} label={delta.label} colors={pillColors} size={changeSize} />
                </div>
            ) : (
                renderedHeadline
            )}

            {resolvedSubtitle != null && resolvedSubtitle !== '' && (
                <div className="mt-1 text-sm opacity-60">{resolvedSubtitle}</div>
            )}

            {sparklineData && theme && (
                <Sparkline
                    data={sparklineData}
                    labels={labels}
                    theme={theme}
                    color={color}
                    height={sparklineHeight}
                    fill={sparklineFill}
                    fillOpacity={sparklineFillOpacity}
                    onHoverIndexChange={setHoverIndex}
                    className={sparklineClassName}
                />
            )}
        </div>
    )
}

interface ChangePillProps {
    positive: boolean
    label: React.ReactNode
    colors: ChangeColor
    size?: 'sm' | 'md'
}

function ChangePill({ positive, label, colors, size = 'sm' }: ChangePillProps): React.ReactElement {
    const sizeClasses = size === 'md' ? 'gap-1.5 px-2.5 py-1 text-sm' : 'gap-1 px-2 py-0.5 text-xs'
    return (
        <div
            className={`inline-flex items-center rounded-full font-medium transition-colors ${sizeClasses}`}
            style={{ background: colors.background, color: colors.foreground }}
        >
            <Chevron up={positive} size={size === 'md' ? 12 : 10} />
            <span className="tabular-nums">{label}</span>
        </div>
    )
}

function Chevron({ up, size = 10 }: { up: boolean; size?: number }): React.ReactElement {
    return (
        <svg
            width={size}
            height={size}
            viewBox="0 0 10 10"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            className={up ? '' : 'rotate-180'}
        >
            <path d="M2 6.5 L5 3.5 L8 6.5" />
        </svg>
    )
}
