import type React from 'react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

import type { HogChartTheme, TooltipConfig, TooltipContext } from '../types'
import { formatValue } from '../utils/format'
import { mergeTheme } from '../utils/theme'

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

interface TooltipPortalProps {
    context: TooltipContext | null
    config?: TooltipConfig
    theme?: Partial<HogChartTheme>
    containerRef: React.RefObject<HTMLElement>
}

export function TooltipPortal({ context, config, theme, containerRef }: TooltipPortalProps): JSX.Element | null {
    const [portalEl, setPortalEl] = useState<HTMLDivElement | null>(null)

    useEffect(() => {
        const el = document.createElement('div')
        el.className = 'hog-charts-tooltip-portal'
        el.setAttribute('data-attr', 'hog-charts-tooltip')
        document.body.appendChild(el)
        setPortalEl(el)
        return () => {
            el.remove()
        }
    }, [])

    useEffect(() => {
        if (!portalEl) {
            return
        }
        if (context) {
            portalEl.style.opacity = '1'
            portalEl.style.pointerEvents = 'none'
        } else {
            portalEl.style.opacity = '0'
            portalEl.style.pointerEvents = 'none'
            config?.onHide?.()
        }
    }, [context, config, portalEl])

    if (!context || !portalEl) {
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
        portalEl
    )
}

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

        let left = caretX + 12
        const top = caretY - tooltip.offsetHeight / 2

        const viewportRight = window.scrollX + document.documentElement.clientWidth
        if (tooltip.offsetWidth > 0 && left + tooltip.offsetWidth > viewportRight - 8) {
            left = caretX - tooltip.offsetWidth - 12
        }

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
