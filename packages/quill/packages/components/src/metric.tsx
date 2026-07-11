import { ChevronDown, ChevronUp } from 'lucide-react'
import * as React from 'react'

import {
    type ChangeColor,
    ChartErrorBoundary,
    computeFallbackChangePercent,
    type MetricChange,
    percentage,
    type ResolvedDelta,
    resolveDelta,
    Sparkline,
    useAnimatedNumber,
    useHoverIntent,
} from '@posthog/quill-charts'
import type { ChartTheme } from '@posthog/quill-charts'
import { Badge, cn, Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@posthog/quill-primitives'

export type { ChangeColor, MetricChange }

// What the root computes once and every part reads. Parts stay dumb: they render a slice of this.
interface MetricContextValue {
    /** Formatted headline — already follows the hovered sparkline point. */
    headlineDisplay: string
    /** Resolved caption (subtitle override → resting subtitle at rest → hovered label). */
    subtitle: React.ReactNode
    /** The change pill's resolved state, or null when there is nothing to show. */
    change: {
        delta: ResolvedDelta
        /** value ≥ 0 — drives the chevron direction. */
        positive: boolean
        /** Change is in the desired direction — drives the Badge color (success vs destructive). */
        good: boolean
        /** Custom pill colors resolved from `positiveColor`/`negativeColor`; overrides the Badge variant. */
        colors?: ChangeColor
        tooltip?: string
    } | null
    /** Sparkline wiring, or null when no series was supplied. */
    sparkline: {
        data: number[]
        labels?: string[]
        theme: ChartTheme
        color?: string
        height: number
        fill: boolean
        fillOpacity: number
        dashedFromIndex?: number
        setHoverIndex: (index: number) => void
    } | null
}

const MetricContext = React.createContext<MetricContextValue | null>(null)

function useMetric(part: string): MetricContextValue {
    const ctx = React.useContext(MetricContext)
    if (ctx == null) {
        throw new Error(`${part} must be rendered inside <Metric>`)
    }
    return ctx
}

const DEFAULT_FORMAT_VALUE = (v: number): string => v.toLocaleString()
const DEFAULT_FORMAT_CHANGE = (p: number): string => {
    // Matches the monolithic MetricCard: `percentage` carries the sign for negatives, we prepend `+`.
    const formatted = percentage(p / 100, 1, true)
    return p > 0 ? `+${formatted}` : formatted
}

export interface MetricProps {
    /** Resting headline number. Defaults to `data[data.length - 1]` when `data` is present;
     *  required when `data` is empty or omitted. */
    value?: number
    /** Series values. When present, a `MetricSparkline` renders and hovering a point swaps the headline. */
    data?: number[]
    /** Labels paired with `data`. Used for the default subtitle on hover. */
    labels?: string[]
    /** Required when `data` is present. */
    theme?: ChartTheme
    /** Sparkline line + fill color. Falls back to `theme.colors[0]`. */
    color?: string
    sparklineHeight?: number
    /** Fill the card's remaining height with the sparkline instead of a fixed `sparklineHeight`. */
    sparklineFill?: boolean
    sparklineFillOpacity?: number
    /** Dash the sparkline from this index onward (e.g. an in-progress trailing period). */
    sparklineDashedFromIndex?: number
    formatValue?: (value: number) => string
    formatChange?: (percent: number) => string
    showChange?: boolean
    /** Fixed comparison pill. Supplied → no hover-driven fallback. Pass `null` to suppress. */
    change?: MetricChange | null
    /** Which direction is "good" — drives the pill color. Defaults to `up`. */
    goodDirection?: 'up' | 'down'
    /** Custom pill colors for a change in the good direction (e.g. user-configured insight colors).
     *  Overrides the Badge `success` variant; omit to keep the semantic variants. */
    positiveColor?: ChangeColor
    /** Custom pill colors for a change in the bad direction. Overrides the Badge `destructive` variant. */
    negativeColor?: ChangeColor
    /** Tooltip shown on hover over the change pill. */
    changeTooltip?: string
    /** Caption shown at rest and on hover. Always wins over `restingSubtitle` and hovered labels. */
    subtitle?: React.ReactNode
    /** Caption shown only while at rest (e.g. `'Avg'`); on hover it yields to the hovered point's label. */
    restingSubtitle?: React.ReactNode
    /** While hovering a sparkline point, swap the resting `change` pill for the hovered point's change
     *  vs the previous point. The resting `change` still shows when not hovering. */
    hoverChangeFromPreviousPoint?: boolean
    animationMs?: number
    /** Dwell (ms) a pointer must settle on the sparkline before the headline follows it. `0` disables. */
    hoverIntentMs?: number
    className?: string
    dataAttr?: string
    onError?: (error: Error, info: React.ErrorInfo) => void
    children: React.ReactNode
}

/**
 * Composable metric tile — a headline number, a `Badge` change pill, and an optional `Sparkline`.
 * `Metric` is content, not a surface: wrap it in `<Card flush>` for the border. The root owns the data
 * and hover behavior and hands every derived display value to its parts via context; you choose the
 * layout by composing the parts. It owns its inline padding (`px-4`) so `MetricSparkline` can bleed out.
 *
 * ```tsx
 * <Card flush>
 *   <Metric data={data} labels={labels} theme={theme} color="#fb7185">
 *     <MetricHeader>
 *       <MetricTitle>Active users</MetricTitle>
 *       <MetricDelta />
 *     </MetricHeader>
 *     <MetricValue />
 *     <MetricSubtitle />
 *     <MetricSparkline />
 *   </Metric>
 * </Card>
 * ```
 */
export function Metric(props: MetricProps): React.ReactElement | null {
    const { onError, ...rest } = props
    return (
        <ChartErrorBoundary onError={onError}>
            <MetricInner {...rest} />
        </ChartErrorBoundary>
    )
}

function MetricInner({
    value,
    data,
    labels,
    theme,
    color,
    sparklineHeight = 120,
    sparklineFill = false,
    sparklineFillOpacity = 0.35,
    sparklineDashedFromIndex,
    formatValue = DEFAULT_FORMAT_VALUE,
    formatChange = DEFAULT_FORMAT_CHANGE,
    showChange = true,
    change,
    goodDirection = 'up',
    positiveColor,
    negativeColor,
    changeTooltip,
    subtitle,
    restingSubtitle,
    hoverChangeFromPreviousPoint = false,
    animationMs = 350,
    hoverIntentMs = 140,
    className,
    dataAttr,
    children,
}: Omit<MetricProps, 'onError'>): React.ReactElement | null {
    const sparklineData = data != null && data.length > 0 && theme != null ? data : null
    const lastIndex = sparklineData ? sparklineData.length - 1 : -1

    const [hoverIndex, setHoverIndex] = React.useState(-1)
    const intentIndex = useHoverIntent(hoverIndex, hoverIntentMs)
    const activeIndex = intentIndex >= 0 ? intentIndex : lastIndex

    const restingValue = value ?? (sparklineData ? sparklineData[lastIndex] : undefined)
    const animationTarget = sparklineData && intentIndex >= 0 ? (sparklineData[intentIndex] ?? 0) : (restingValue ?? 0)
    const animatedValue = useAnimatedNumber(animationTarget, animationMs)

    const baselineValue = React.useMemo(
        () => sparklineData?.find((v) => v !== 0 && Number.isFinite(v)),
        [sparklineData]
    )

    const ctx = React.useMemo<MetricContextValue | null>(() => {
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

        // A supplied `change` shows at rest; while hovering with `hoverChangeFromPreviousPoint` it yields
        // to the point-vs-previous delta — except an explicit `null` (suppress) stays suppressed on hover.
        const delta = resolveDelta({
            showChange,
            change: usePrevPointHover && change !== null ? undefined : change,
            fallbackChangePercent,
            formatChange,
        })
        const positive = delta != null && delta.value >= 0
        const good = goodDirection === 'up' ? positive : !positive

        return {
            headlineDisplay: sparklineData ? formatValue(animatedValue) : formatValue(restingValue),
            subtitle:
                subtitle ?? (intentIndex < 0 && restingSubtitle != null ? restingSubtitle : labels?.[activeIndex]),
            change:
                delta != null
                    ? {
                          delta,
                          positive,
                          good,
                          colors: good ? positiveColor : negativeColor,
                          // The tooltip describes the resting comparison, so hide it on the per-point delta.
                          tooltip: usePrevPointHover ? undefined : changeTooltip,
                      }
                    : null,
            sparkline: sparklineData
                ? {
                      data: sparklineData,
                      labels,
                      theme: theme!,
                      color,
                      height: sparklineHeight,
                      fill: sparklineFill,
                      fillOpacity: sparklineFillOpacity,
                      dashedFromIndex: sparklineDashedFromIndex,
                      setHoverIndex,
                  }
                : null,
        }
    }, [
        restingValue,
        sparklineData,
        activeIndex,
        intentIndex,
        hoverChangeFromPreviousPoint,
        baselineValue,
        showChange,
        change,
        formatChange,
        changeTooltip,
        goodDirection,
        positiveColor,
        negativeColor,
        formatValue,
        animatedValue,
        subtitle,
        restingSubtitle,
        labels,
        theme,
        color,
        sparklineHeight,
        sparklineFill,
        sparklineFillOpacity,
        sparklineDashedFromIndex,
    ])

    if (ctx == null) {
        return null
    }

    // Metric is content, not a surface — wrap it in `<Card flush>` for the border. It owns its inline
    // padding (`px-4`, like `CardContent`) so the text insets and a `MetricSparkline` can bleed back out
    // with `-mx-4`; block padding + the bottom edge come from the wrapping card.
    return (
        <MetricContext.Provider value={ctx}>
            <div data-attr={dataAttr} className={cn('flex h-full flex-col px-4', className)}>
                {children}
            </div>
        </MetricContext.Provider>
    )
}

/** Header row: title on the left, change pill (or anything) on the right. */
export function MetricHeader({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return <div className={cn('flex items-start justify-between gap-2', className)} {...props} />
}

export function MetricTitle({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return <div className={cn('text-sm font-medium', className)} {...props} />
}

/** Headline number. Follows the hovered sparkline point; pass `children` to render your own, or a
 *  `text-*` class to resize it (cn lets your size win over the default `text-4xl`). */
export function MetricValue({ className, children, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    const { headlineDisplay } = useMetric('MetricValue')
    return (
        <div className={cn('min-w-0 truncate text-4xl font-bold tracking-tight tabular-nums', className)} {...props}>
            {children ?? headlineDisplay}
        </div>
    )
}

/** Change pill — a `Badge` (success/destructive by `goodDirection`, or the root's custom
 *  `positiveColor`/`negativeColor`) with a directional chevron. Renders nothing when there is no
 *  resolved delta. Carries its own `TooltipProvider`, so `changeTooltip` needs no app-root setup. */
export function MetricDelta({
    className,
    size = 'sm',
}: {
    className?: string
    /** `md` renders the larger pill the metric insight uses inline next to the headline. */
    size?: 'sm' | 'md'
}): React.ReactElement | null {
    const { change } = useMetric('MetricDelta')
    if (change == null) {
        return null
    }
    const Chevron = change.positive ? ChevronUp : ChevronDown
    const badge = (
        <Badge
            variant={change.colors != null ? 'default' : change.good ? 'success' : 'destructive'}
            className={cn(
                'gap-0.5 rounded-full tabular-nums',
                size === 'md' && 'h-auto gap-1 px-2.5 py-1 text-sm [&>svg]:size-3!',
                className
            )}
            // Dynamic user-configured colors can't be Tailwind classes; inline style wins over the variant.
            style={
                change.colors != null
                    ? { background: change.colors.background, color: change.colors.foreground }
                    : undefined
            }
            data-attr="metric-change-pill"
        >
            <Chevron className="size-3" />
            {change.delta.label}
        </Badge>
    )
    if (change.tooltip == null) {
        return badge
    }
    // Badge isn't a forwardRef component, so it can't be the `render` target — anchor on a span.
    return (
        <TooltipProvider>
            <Tooltip>
                <TooltipTrigger render={<span className="inline-flex" />}>{badge}</TooltipTrigger>
                <TooltipContent>{change.tooltip}</TooltipContent>
            </Tooltip>
        </TooltipProvider>
    )
}

/** Caption under the headline. Renders nothing when empty; pass `children` to override. */
export function MetricSubtitle({
    className,
    children,
    ...props
}: React.ComponentProps<'div'>): React.ReactElement | null {
    const { subtitle } = useMetric('MetricSubtitle')
    const content = children ?? subtitle
    if (content == null || content === '') {
        return null
    }
    return (
        <div className={cn('text-sm opacity-60', className)} data-attr="metric-subtitle" {...props}>
            {content}
        </div>
    )
}

/** Sparkline, bled out to the card edges. Renders nothing when no series was supplied to the root. */
export function MetricSparkline({
    className = '-mx-4 -mb-4 mt-4 flex-1',
}: {
    className?: string
}): React.ReactElement | null {
    const { sparkline } = useMetric('MetricSparkline')
    if (sparkline == null) {
        return null
    }
    // A fixed-height sparkline drops to the bottom of a taller card via `mt-auto`; a filling sparkline
    // grows into the free space itself, so it must not also claim that space with a margin. `-mx-4`/`-mb-4`
    // cancel the card's content padding so the chart reaches the left/right/bottom edges. The 6px shift
    // pushes the canvas's bottom hover-ring margin past the card edge so the line rests on it —
    // always applied, so callers overriding `className` only manage margins.
    const pinBottom = sparkline.fill ? '' : 'mt-auto'
    return (
        <Sparkline
            data={sparkline.data}
            labels={sparkline.labels}
            theme={sparkline.theme}
            color={sparkline.color}
            height={sparkline.height}
            fill={sparkline.fill}
            fillOpacity={sparkline.fillOpacity}
            dashedFromIndex={sparkline.dashedFromIndex}
            onHoverIndexChange={sparkline.setHoverIndex}
            className={cn('relative top-[6px]', pinBottom, className)}
            dataAttr="metric-sparkline"
        />
    )
}
