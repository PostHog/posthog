import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

import { formatValue } from '../format'
import { mergeTheme } from '../theme'
import type { HogChartTheme, TooltipConfig, TooltipContext } from '../types'

// ---------------------------------------------------------------------------
// Default built-in tooltip
// ---------------------------------------------------------------------------

/** Clean, minimal tooltip rendered when no custom `render` function is provided. */
export function DefaultTooltip({
    context,
    theme: themeOverrides,
    formatValueFn,
}: {
    context: TooltipContext
    theme?: Partial<HogChartTheme>
    formatValueFn?: TooltipConfig['formatValue']
}): JSX.Element {
    const theme = mergeTheme(themeOverrides)

    return (
        <div
            style={{
                backgroundColor: theme.tooltipBackground,
                color: theme.tooltipColor,
                borderRadius: theme.tooltipBorderRadius,
                padding: '8px 12px',
                fontFamily: theme.fontFamily,
                fontSize: theme.fontSize,
                boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
                pointerEvents: 'none',
                maxWidth: 320,
                zIndex: 1000,
            }}
        >
            {context.label && (
                <div
                    style={{
                        fontWeight: 600,
                        marginBottom: context.points.length > 0 ? 6 : 0,
                        fontSize: (theme.fontSize ?? 12) - 1,
                        opacity: 0.7,
                    }}
                >
                    {context.label}
                </div>
            )}
            {context.points.map((point) => (
                <div
                    key={`${point.seriesIndex}-${point.pointIndex}`}
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 8,
                        padding: '2px 0',
                    }}
                >
                    <span
                        style={{
                            width: 8,
                            height: 8,
                            borderRadius: '50%',
                            backgroundColor: point.color,
                            flexShrink: 0,
                        }}
                    />
                    <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {point.seriesLabel}
                    </span>
                    <span style={{ fontWeight: 600, fontVariantNumeric: 'tabular-nums', marginLeft: 12 }}>
                        {formatValueFn
                            ? formatValueFn(point.value, point.seriesIndex)
                            : formatValue(point.value, 'compact')}
                    </span>
                </div>
            ))}
        </div>
    )
}

// ---------------------------------------------------------------------------
// Tooltip portal & positioning system
// ---------------------------------------------------------------------------

interface TooltipPortalProps {
    context: TooltipContext | null
    config?: TooltipConfig
    theme?: Partial<HogChartTheme>
    /** The chart wrapper element — used for scoping the portal. */
    containerRef: React.RefObject<HTMLElement>
}

/**
 * Manages the tooltip lifecycle:
 * - Creates a portal element attached to document.body
 * - Positions it relative to the chart using canvas coordinates
 * - Renders either the custom `render` function or the default tooltip
 * - Handles show/hide with proper cleanup
 */
export function TooltipPortal({ context, config, theme, containerRef }: TooltipPortalProps): JSX.Element | null {
    const portalRef = useRef<HTMLDivElement | null>(null)

    // Lazily create the portal container
    if (!portalRef.current) {
        const el = document.createElement('div')
        el.className = 'hog-charts-tooltip-portal'
        el.setAttribute('data-attr', 'hog-charts-tooltip')
        document.body.appendChild(el)
        portalRef.current = el
    }

    // Clean up portal on unmount
    useEffect(() => {
        const el = portalRef.current
        return () => {
            if (el) {
                el.remove()
            }
        }
    }, [])

    // Hide when context is null
    useEffect(() => {
        if (!context && portalRef.current) {
            portalRef.current.style.opacity = '0'
            portalRef.current.style.pointerEvents = 'none'
            config?.onHide?.()
        }
    }, [context, config])

    if (!context || !portalRef.current) {
        return null
    }

    const content = config?.render ? (
        config.render(context)
    ) : (
        <DefaultTooltip context={context} theme={theme} formatValueFn={config?.formatValue} />
    )

    return createPortal(
        <TooltipPositioner context={context} containerRef={containerRef}>
            {content}
        </TooltipPositioner>,
        portalRef.current
    )
}

// ---------------------------------------------------------------------------
// Positioning logic
// ---------------------------------------------------------------------------

function TooltipPositioner({
    context,
    containerRef,
    children,
}: {
    context: TooltipContext
    containerRef: React.RefObject<HTMLElement>
    children: React.ReactNode
}): JSX.Element {
    const tooltipRef = useRef<HTMLDivElement>(null)
    const [position, setPosition] = useState<{ left: number; top: number }>({ left: 0, top: 0 })

    useEffect(() => {
        if (!tooltipRef.current || !containerRef.current) {
            return
        }

        const tooltip = tooltipRef.current
        const bounds = context.chartBounds
        const caretX = bounds.left + window.scrollX + context.position.x
        const caretY = bounds.top + window.scrollY + context.position.y

        // Position to the right of the cursor by default
        let left = caretX + 12
        const top = caretY - tooltip.offsetHeight / 2

        // Flip to the left if we'd overflow the viewport
        const viewportRight = window.scrollX + document.documentElement.clientWidth
        if (tooltip.offsetWidth > 0 && left + tooltip.offsetWidth > viewportRight - 8) {
            left = caretX - tooltip.offsetWidth - 12
        }

        // Clamp to viewport edges
        left = Math.max(window.scrollX + 8, left)
        const viewportBottom = window.scrollY + document.documentElement.clientHeight
        const clampedTop = Math.min(
            Math.max(window.scrollY + 8, top),
            viewportBottom - Math.max(tooltip.offsetHeight, 0) - 8
        )

        setPosition({ left, top: clampedTop })
    }, [context, containerRef])

    return (
        <div
            ref={tooltipRef}
            style={{
                position: 'absolute',
                left: position.left,
                top: position.top,
                zIndex: 1000,
                opacity: 1,
                transition: 'opacity 0.15s ease, left 0.1s ease, top 0.1s ease',
                pointerEvents: 'none',
            }}
        >
            {children}
        </div>
    )
}

// ---------------------------------------------------------------------------
// Hook for Chart.js integration
// ---------------------------------------------------------------------------

/**
 * Hook that bridges Chart.js tooltip callbacks to the HogCharts tooltip system.
 *
 * Returns:
 * - `tooltipContext`: current tooltip state (or null when hidden)
 * - `onTooltip`: callback to pass into Chart.js external tooltip handler
 * - `onTooltipHide`: callback for when mouse leaves the chart
 */
export function useTooltipState(): {
    tooltipContext: TooltipContext | null
    showTooltip: (context: TooltipContext) => void
    hideTooltip: () => void
} {
    const [tooltipContext, setTooltipContext] = useState<TooltipContext | null>(null)
    const hideTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

    const showTooltip = useCallback((ctx: TooltipContext) => {
        if (hideTimeoutRef.current) {
            clearTimeout(hideTimeoutRef.current)
            hideTimeoutRef.current = null
        }
        setTooltipContext(ctx)
    }, [])

    const hideTooltip = useCallback(() => {
        // Small delay to allow moving to the tooltip itself (for interactive tooltips)
        hideTimeoutRef.current = setTimeout(() => {
            setTooltipContext(null)
        }, 100)
    }, [])

    useEffect(() => {
        return () => {
            if (hideTimeoutRef.current) {
                clearTimeout(hideTimeoutRef.current)
            }
        }
    }, [])

    return { tooltipContext, showTooltip, hideTooltip }
}
