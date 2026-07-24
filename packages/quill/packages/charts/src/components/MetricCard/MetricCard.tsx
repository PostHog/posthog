import React, { useMemo, useState } from 'react'

import { Sparkline } from '../../charts/Sparkline/Sparkline'
import { ChartErrorBoundary } from '../../core/ChartErrorBoundary'
import type { ChartTheme, Series, TooltipContext } from '../../core/types'
import {
    ArrowRightIcon,
    type ChangeColor,
    ChangePill,
    computeFallbackChangePercent,
    DEFAULT_FORMAT_CHANGE,
    DEFAULT_FORMAT_VALUE,
    DEFAULT_NEGATIVE_COLOR,
    DEFAULT_POSITIVE_COLOR,
    HoverTooltip,
    InfoIcon,
} from './internals'
import { type MetricChange, resolveDelta } from './resolveDelta'
import { useAnimatedNumber } from './useAnimatedNumber'
import { useHoverIntent } from './useHoverIntent'

export type { MetricChange }
export type { ChangeColor }

export interface MetricCardProps {
    title: React.ReactNode
    /** Resting headline number. Defaults to `data[data.length - 1]` when `data` is present;
     *  required when `data` is empty or omitted. */
    value?: number
    /** Series values. When present, a sparkline renders below the headline and hovering a point
     *  swaps the headline. */
    data?: number[]
    /** Multi-series sparkline (one line per series). When set, `data`, `color`, and
     *  `sparklineDashedFromIndex` are ignored — express those per series. The headline, hover, and
     *  change pill operate on the per-index total across all series. */
    series?: Series[]
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
    /** Dash the sparkline from this index onward (e.g. an in-progress trailing period). */
    sparklineDashedFromIndex?: number
    /** Render prop for the sparkline's hover tooltip. Off by default (hovering only scrubs the
     *  headline); supply this — e.g. `(ctx) => <DefaultTooltip {...ctx} />` — to also show a tooltip. */
    sparklineTooltip?: (ctx: TooltipContext) => React.ReactNode
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
    /** Tooltip shown on hover over the change pill, e.g. explaining what it compares. */
    changeTooltip?: string
    positiveColor?: ChangeColor
    negativeColor?: ChangeColor
    /** Caption under the headline. Defaults to `labels[activeIndex]` when a sparkline is present.
     *  Always wins — shown at rest and on hover. */
    subtitle?: React.ReactNode
    /** Caption shown only while at rest (e.g. `'Avg'`); on hover it yields to the hovered point's
     *  label. Ignored when `subtitle` is set. */
    restingSubtitle?: React.ReactNode
    /** While hovering a sparkline point, replace the resting `change` pill with the change from the
     *  previous point (`(data[i] - data[i-1]) / |data[i-1]|`). At the first point there is no previous,
     *  so the pill is hidden. The resting `change` (or fallback) still shows when not hovering. */
    hoverChangeFromPreviousPoint?: boolean
    animationMs?: number
    /** Dwell (ms) a pointer must settle on the sparkline before the headline follows it.
     *  Keeps a quick pass-through from grabbing attention. `0` disables the gating. */
    hoverIntentMs?: number
    /** Info tooltip shown on a small icon next to the title (e.g. what the metric measures). */
    titleTooltip?: React.ReactNode
    /** Makes the whole card clickable (e.g. to drill into the underlying rows) — adds a pointer
     *  cursor, a keyboard-activatable role, and a drill affordance next to the title. */
    onClick?: () => void
    /** Tooltip shown on the drill affordance when `onClick` is set. */
    onClickTooltip?: string
    /** Render a skeleton placeholder instead of the card contents while data loads. */
    loading?: boolean
    /** Content rendered below the sparkline, e.g. a deep-link to the underlying data. */
    footer?: React.ReactNode
    className?: string
    dataAttr?: string
    onError?: (error: Error, info: React.ErrorInfo) => void
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
    series,
    labels,
    theme,
    color,
    sparklineHeight = 120,
    sparklineFill = false,
    sparklineFillOpacity = 0.35,
    sparklineClassName = 'mt-4',
    sparklineDashedFromIndex,
    sparklineTooltip,
    formatValue = DEFAULT_FORMAT_VALUE,
    formatChange = DEFAULT_FORMAT_CHANGE,
    showChange = true,
    change,
    goodDirection = 'up',
    changeSize = 'sm',
    changeInline = false,
    changeTooltip,
    positiveColor = DEFAULT_POSITIVE_COLOR,
    negativeColor = DEFAULT_NEGATIVE_COLOR,
    subtitle,
    restingSubtitle,
    hoverChangeFromPreviousPoint = false,
    animationMs = 350,
    hoverIntentMs = 140,
    titleTooltip,
    onClick,
    onClickTooltip,
    loading = false,
    footer,
    className,
    dataAttr,
}: Omit<MetricCardProps, 'onError'>): React.ReactElement | null {
    // Multi-series draws N lines; the metric engine (headline, hover, change) still runs on a single
    // number[] — the per-index total across those series — so a stat tile reads as one number.
    const multiSeries = series != null && series.length > 0 && theme != null ? series : null
    const sparklineData = useMemo<number[] | null>(() => {
        if (multiSeries) {
            const length = Math.max(0, ...multiSeries.map((s) => s.data.length))
            return Array.from({ length }, (_, i) => multiSeries.reduce((acc, s) => acc + (s.data[i] ?? 0), 0))
        }
        return data != null && data.length > 0 && theme != null ? data : null
    }, [multiSeries, data, theme])
    const lastIndex = sparklineData ? sparklineData.length - 1 : -1

    const [hoverIndex, setHoverIndex] = useState(-1)
    const intentIndex = useHoverIntent(hoverIndex, hoverIntentMs)
    const activeIndex = intentIndex >= 0 ? intentIndex : lastIndex

    const restingValue = value ?? (sparklineData ? sparklineData[lastIndex] : undefined)
    const animationTarget = sparklineData && intentIndex >= 0 ? (sparklineData[intentIndex] ?? 0) : (restingValue ?? 0)
    const animatedValue = useAnimatedNumber(animationTarget, animationMs)

    const baselineValue = useMemo(() => sparklineData?.find((v) => v !== 0 && Number.isFinite(v)), [sparklineData])

    if (loading) {
        return (
            <div className={`flex flex-col w-full ${className ?? ''}`} data-attr={dataAttr}>
                {title != null && <div className="h-4 w-24 animate-pulse rounded bg-current opacity-10" />}
                <div
                    className={`h-9 w-28 animate-pulse rounded bg-current opacity-10${title != null ? ' mt-3' : ''}`}
                />
                <div
                    className="mt-4 w-full animate-pulse rounded bg-current opacity-10"
                    // Dynamic height mirrors the eventual sparkline so the card doesn't jump on load.
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ height: sparklineFill ? '100%' : sparklineHeight }}
                    data-attr="metric-card-loading-sparkline"
                />
            </div>
        )
    }

    if (restingValue == null) {
        return null
    }

    const liveValue = sparklineData ? (sparklineData[activeIndex] ?? 0) : restingValue
    const usePrevPointHover = hoverChangeFromPreviousPoint && intentIndex >= 0 && sparklineData != null
    const fallbackChangePercent = computeFallbackChangePercent(
        sparklineData,
        usePrevPointHover,
        intentIndex,
        liveValue,
        baselineValue
    )

    // A supplied `change` shows at rest; while hovering with `hoverChangeFromPreviousPoint` it yields to
    // the point-vs-previous delta — except an explicit `null` (suppress) stays suppressed across hover.
    const delta = resolveDelta({
        showChange,
        change: usePrevPointHover && change !== null ? undefined : change,
        fallbackChangePercent,
        formatChange,
    })
    // The tooltip describes the resting comparison, so hide it once the pill shows the per-point delta.
    const activeChangeTooltip = usePrevPointHover ? undefined : changeTooltip
    const headlineDisplay = sparklineData ? formatValue(animatedValue) : formatValue(restingValue)
    const resolvedSubtitle =
        subtitle ?? (intentIndex < 0 && restingSubtitle != null ? restingSubtitle : labels?.[activeIndex])

    const positive = delta != null && delta.value >= 0
    const isGood = goodDirection === 'up' ? positive : !positive
    const pillColors = isGood ? positiveColor : negativeColor

    const headerDelta = delta != null && !changeInline ? delta : null
    const showHeader = title != null || headerDelta != null
    const headerJustify = title != null ? 'justify-between' : 'justify-end'
    const renderedHeadline = (
        <div className={`text-4xl font-bold tracking-tight tabular-nums${showHeader ? ' mt-2' : ''}`}>
            {headlineDisplay}
        </div>
    )

    const clickable = onClick != null
    const interactiveProps = clickable
        ? {
              role: 'button' as const,
              tabIndex: 0,
              onClick,
              onKeyDown: (e: React.KeyboardEvent<HTMLDivElement>) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      onClick?.()
                  }
              },
          }
        : {}

    return (
        <div
            className={`flex flex-col w-full${clickable ? ' cursor-pointer transition-colors hover:border-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50' : ''} ${className ?? ''}`}
            data-attr={dataAttr}
            {...interactiveProps}
        >
            {showHeader && (
                <div className={`flex items-start gap-2 ${headerJustify}`}>
                    {title != null && (
                        <div className="flex items-center gap-1 text-sm font-medium">
                            <span>{title}</span>
                            {titleTooltip != null && (
                                <HoverTooltip content={titleTooltip}>
                                    <span
                                        className="inline-flex cursor-help opacity-50"
                                        data-attr="metric-card-title-info"
                                        onClick={(e) => e.stopPropagation()}
                                    >
                                        <InfoIcon />
                                    </span>
                                </HoverTooltip>
                            )}
                            {clickable && (
                                <HoverTooltip content={onClickTooltip ?? 'View details'}>
                                    <span className="inline-flex opacity-40" data-attr="metric-card-drill">
                                        <ArrowRightIcon />
                                    </span>
                                </HoverTooltip>
                            )}
                        </div>
                    )}
                    {headerDelta != null && (
                        <ChangePill
                            positive={positive}
                            label={headerDelta.label}
                            colors={pillColors}
                            size={changeSize}
                            tooltip={activeChangeTooltip}
                        />
                    )}
                </div>
            )}

            {changeInline && delta != null ? (
                <div className="flex items-center justify-between gap-2">
                    {renderedHeadline}
                    <ChangePill
                        positive={positive}
                        label={delta.label}
                        colors={pillColors}
                        size={changeSize}
                        tooltip={activeChangeTooltip}
                    />
                </div>
            ) : (
                renderedHeadline
            )}

            {resolvedSubtitle != null && resolvedSubtitle !== '' && (
                <div className="mt-1 text-sm opacity-60" data-attr="metric-card-subtitle">
                    {resolvedSubtitle}
                </div>
            )}

            {sparklineData && theme && (
                <Sparkline
                    data={multiSeries ? undefined : sparklineData}
                    series={multiSeries ?? undefined}
                    labels={labels}
                    theme={theme}
                    color={color}
                    height={sparklineHeight}
                    fill={sparklineFill}
                    fillOpacity={sparklineFillOpacity}
                    dashedFromIndex={sparklineDashedFromIndex}
                    tooltip={sparklineTooltip}
                    onHoverIndexChange={setHoverIndex}
                    className={sparklineClassName}
                    dataAttr="metric-card-sparkline"
                />
            )}

            {footer != null && (
                <div
                    className="mt-2 text-center text-xs"
                    data-attr="metric-card-footer"
                    // A footer link should navigate, not trigger the card's drill onClick.
                    onClick={(e) => e.stopPropagation()}
                >
                    {footer}
                </div>
            )}
        </div>
    )
}
