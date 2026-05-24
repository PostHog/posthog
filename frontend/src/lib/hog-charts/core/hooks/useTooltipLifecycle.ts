import React, { useCallback, useEffect, useState } from 'react'

import type { TooltipContext } from '../types'

/** Value-equality check used by the pinned-rebuild effect to skip no-op updates. Compares
 *  dataIndex, label, position, and per-row value/color/series.key/series.label. Series are
 *  compared by stable `key` rather than identity because the parent typically rebuilds the
 *  resolved-series array on every render. */
export function isTooltipContextEquivalent<Meta>(a: TooltipContext<Meta>, b: TooltipContext<Meta>): boolean {
    if (a.dataIndex !== b.dataIndex || a.label !== b.label) {
        return false
    }
    if (a.position.x !== b.position.x || a.position.y !== b.position.y) {
        return false
    }
    if (a.seriesData.length !== b.seriesData.length) {
        return false
    }
    for (let i = 0; i < a.seriesData.length; i++) {
        const ai = a.seriesData[i]
        const bi = b.seriesData[i]
        if (
            ai.value !== bi.value ||
            ai.color !== bi.color ||
            ai.fraction !== bi.fraction ||
            ai.series.key !== bi.series.key ||
            ai.series.label !== bi.series.label
        ) {
            return false
        }
    }
    return true
}

export interface UseTooltipLifecycleOptions<Meta> {
    wrapperRef: React.RefObject<HTMLDivElement>
    /** Rebuilds the pinned tooltip context when `rebuildDeps` change while a pin is held. Receives
     *  the previous pinned context (without `isPinned`/`onUnpin` mutations re-applied — the lifecycle
     *  re-pins after the rebuild). Return `null` to drop the pin (e.g. the data point no longer exists). */
    rebuildPinnedCtx: (prev: TooltipContext<Meta>) => TooltipContext<Meta> | null
    /** Inputs that should retrigger a pinned rebuild (typically series, labels, scales, dimensions). */
    rebuildDeps: React.DependencyList
}

export interface UseTooltipLifecycleResult<Meta> {
    hoverIndex: number
    hoverPosition: { x: number; y: number } | null
    tooltipCtx: TooltipContext<Meta> | null
    /** Sets hover index + position together. Geometry hooks call this when the cursor enters/moves over a data point. */
    setHover: (index: number, position: { x: number; y: number } | null) => void
    /** Direct setter for the tooltip context. Geometry hooks use this to publish a freshly-built ctx on mousemove. */
    setTooltipCtx: React.Dispatch<React.SetStateAction<TooltipContext<Meta> | null>>
    isPinned: boolean
    /** Clear everything — hover index, hover position, tooltip context (pinned or not). */
    clearTooltip: () => void
    /** Drop only the pin, leaving hover state intact. Bound to `TooltipContext.onUnpin`. */
    unpin: () => void
    /** Promote the current tooltipCtx to pinned. No-op when there's no current ctx. */
    pin: () => void
}

/** Geometry-independent tooltip state and dismiss lifecycle.
 *
 *  Owns: tooltipCtx (and the boolean `isPinned`), hoverIndex/hoverPosition, the three dismiss
 *  effects (scroll outside the chart, click outside, Escape), and the pinned-rebuild effect
 *  with its value-equivalence bail.
 *
 *  Does NOT own: cursor → index hit-testing (cartesian or radial), or anchor positioning. Geometry
 *  hooks compute those and call `setHover` + `setTooltipCtx` to publish results, and pass a
 *  `rebuildPinnedCtx` callback so the lifecycle can refresh the pin when its inputs change. */
export function useTooltipLifecycle<Meta = unknown>({
    wrapperRef,
    rebuildPinnedCtx,
    rebuildDeps,
}: UseTooltipLifecycleOptions<Meta>): UseTooltipLifecycleResult<Meta> {
    const [hoverIndex, setHoverIndex] = useState<number>(-1)
    const [hoverPosition, setHoverPosition] = useState<{ x: number; y: number } | null>(null)
    const [tooltipCtx, setTooltipCtx] = useState<TooltipContext<Meta> | null>(null)

    const setHover = useCallback((index: number, position: { x: number; y: number } | null) => {
        setHoverIndex(index)
        setHoverPosition(position)
    }, [])

    const clearTooltip = useCallback(() => {
        setHoverIndex(-1)
        setHoverPosition(null)
        setTooltipCtx(null)
    }, [])

    const unpin = useCallback(() => {
        setTooltipCtx((prev) => (prev?.isPinned ? null : prev))
    }, [])

    const isPinned = tooltipCtx?.isPinned ?? false

    const pin = useCallback(() => {
        setTooltipCtx((prev) => (prev && !prev.isPinned ? { ...prev, isPinned: true, onUnpin: unpin } : prev))
    }, [unpin])

    // Rebuild or clear the pinned tooltip when its underlying inputs change. Without this,
    // the pin keeps stale values at stale pixel positions after the parent updates series /
    // labels / scales / dimensions.
    useEffect(() => {
        if (!isPinned) {
            return
        }
        setTooltipCtx((prev) => {
            if (!prev || !prev.isPinned) {
                return prev
            }
            const fresh = rebuildPinnedCtx(prev)
            if (!fresh) {
                return null
            }
            // Skip identity churn when the rebuilt context is value-equal to the previous one.
            if (isTooltipContextEquivalent(prev, fresh)) {
                return prev
            }
            return { ...fresh, isPinned: true, onUnpin: unpin }
        })
        // Omitted on purpose:
        //   - isPinned / tooltipCtx — would feedback-loop with setTooltipCtx
        //   - unpin — stable for the hook's lifetime (useCallback([]))
        //   - rebuildPinnedCtx — read live via the closure; caller is responsible for stability if it
        //     wants to avoid extra rebuilds (typically wrapped in useCallback by the geometry hook)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, rebuildDeps)

    // Dismiss the tooltip on scroll — pinned or not — since the anchor moves with the page and
    // a stale tooltip is worse than no tooltip.
    const tooltipShown = tooltipCtx !== null
    useEffect(() => {
        if (!tooltipShown) {
            return
        }
        const handleScroll = (e: Event): void => {
            // Allow scrolling inside the tooltip (long pinned content) or the chart wrapper
            // (a nested legend) without dismissing.
            const target = e.target
            if (target instanceof Element) {
                if (target.closest('[data-hog-charts-tooltip]')) {
                    return
                }
                if (wrapperRef.current?.contains(target)) {
                    return
                }
            }
            clearTooltip()
        }
        window.addEventListener('scroll', handleScroll, { passive: true, capture: true })
        return () => {
            window.removeEventListener('scroll', handleScroll, true)
        }
    }, [tooltipShown, wrapperRef, clearTooltip])

    // Dismiss listeners for pinned tooltip (click outside, Escape).
    useEffect(() => {
        if (!isPinned) {
            return
        }

        const handleClickOutside = (e: MouseEvent): void => {
            const target = e.target
            if (target instanceof Element && target.closest('[data-hog-charts-tooltip]')) {
                return
            }
            const wrapper = wrapperRef.current
            if (wrapper && !wrapper.contains(target as Node)) {
                clearTooltip()
            }
        }

        const handleKeyDown = (e: KeyboardEvent): void => {
            if (e.key === 'Escape') {
                clearTooltip()
            }
        }

        // Delay click listener so the pinning click doesn't immediately unpin.
        const timer = setTimeout(() => {
            document.addEventListener('click', handleClickOutside, { passive: true })
        }, 0)
        document.addEventListener('keydown', handleKeyDown, { passive: true })

        return () => {
            clearTimeout(timer)
            document.removeEventListener('click', handleClickOutside)
            document.removeEventListener('keydown', handleKeyDown)
        }
    }, [isPinned, wrapperRef, clearTooltip])

    return {
        hoverIndex,
        hoverPosition,
        tooltipCtx,
        setHover,
        setTooltipCtx,
        isPinned,
        clearTooltip,
        unpin,
        pin,
    }
}
