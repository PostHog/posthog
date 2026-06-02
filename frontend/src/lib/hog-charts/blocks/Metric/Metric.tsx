import React, { useMemo, useState } from 'react'

import { Sparkline } from '../../charts/Sparkline/Sparkline'
import { ChartErrorBoundary } from '../../core/ChartErrorBoundary'
import type { ChartTheme } from '../../core/types'
import { percentage } from '../../utils/format'
import { type MetricChange, resolveDelta } from './resolveDelta'
import { useAnimatedNumber } from './useAnimatedNumber'

export type { MetricChange }

export interface ChangeColor {
    background: string
    foreground: string
}

export interface MetricProps {
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
    sparklineFillOpacity?: number
    sparklineClassName?: string
    formatValue?: (value: number) => string
    formatChange?: (percent: number) => string
    showChange?: boolean
    /** Fixed comparison pill. Supplied → no hover-driven fallback. Pass `null` to suppress. */
    change?: MetricChange | null
    goodDirection?: 'up' | 'down'
    positiveColor?: ChangeColor
    negativeColor?: ChangeColor
    /** Caption under the headline. Defaults to `labels[activeIndex]` when a sparkline is present. */
    subtitle?: React.ReactNode
    animationMs?: number
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

export function Metric(props: MetricProps): React.ReactElement | null {
    const { onError, ...rest } = props
    return (
        <ChartErrorBoundary onError={onError}>
            <MetricInner {...rest} />
        </ChartErrorBoundary>
    )
}

function MetricInner({
    title,
    value,
    data,
    labels,
    theme,
    color,
    sparklineHeight = 120,
    sparklineFillOpacity = 0.35,
    sparklineClassName = 'mt-4',
    formatValue = DEFAULT_FORMAT_VALUE,
    formatChange = DEFAULT_FORMAT_CHANGE,
    showChange = true,
    change,
    goodDirection = 'up',
    positiveColor = DEFAULT_POSITIVE_COLOR,
    negativeColor = DEFAULT_NEGATIVE_COLOR,
    subtitle,
    animationMs = 350,
    className,
    dataAttr,
}: Omit<MetricProps, 'onError'>): React.ReactElement | null {
    const sparklineData = data != null && data.length > 0 && theme != null ? data : null
    const lastIndex = sparklineData ? sparklineData.length - 1 : -1

    const [hoverIndex, setHoverIndex] = useState(-1)
    const activeIndex = hoverIndex >= 0 ? hoverIndex : lastIndex

    const restingValue = value ?? (sparklineData ? sparklineData[lastIndex] : undefined)
    const animationTarget = sparklineData && hoverIndex >= 0 ? (sparklineData[hoverIndex] ?? 0) : (restingValue ?? 0)
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
    const resolvedSubtitle = subtitle ?? labels?.[activeIndex] ?? ' '

    const positive = delta != null && delta.value >= 0
    const isGood = goodDirection === 'up' ? positive : !positive
    const pillColors = isGood ? positiveColor : negativeColor

    return (
        <div className={`flex flex-col w-full ${className ?? ''}`} data-attr={dataAttr}>
            <div className="flex items-start justify-between gap-2">
                <div className="text-sm font-medium">{title}</div>
                {delta != null && <ChangePill positive={positive} label={delta.label} colors={pillColors} />}
            </div>

            <div className="mt-2 text-4xl font-bold tracking-tight tabular-nums">{headlineDisplay}</div>

            <div className="mt-1 text-sm opacity-60">{resolvedSubtitle}</div>

            {sparklineData && theme && (
                <Sparkline
                    data={sparklineData}
                    labels={labels}
                    theme={theme}
                    color={color}
                    height={sparklineHeight}
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
}

function ChangePill({ positive, label, colors }: ChangePillProps): React.ReactElement {
    return (
        <div
            className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium transition-colors"
            style={{ background: colors.background, color: colors.foreground }}
        >
            <Chevron up={positive} />
            <span className="tabular-nums">{label}</span>
        </div>
    )
}

function Chevron({ up }: { up: boolean }): React.ReactElement {
    return (
        <svg
            width="10"
            height="10"
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
