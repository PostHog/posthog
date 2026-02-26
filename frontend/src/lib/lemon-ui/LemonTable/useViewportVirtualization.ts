import { RefObject, useCallback, useEffect, useState } from 'react'

export interface ViewportVirtualizationConfig {
    /** Total number of rows to virtualize */
    rowCount: number
    /** Estimated height of each row in pixels. Used for calculating spacer sizes. */
    estimatedRowHeight: number
    /** Number of extra rows to render beyond the visible area (default: 10) */
    overscan?: number
    /** Whether virtualization is enabled (default: true) */
    enabled?: boolean
}

export interface ViewportVirtualizationResult {
    startIndex: number
    endIndex: number
    topSpacerHeight: number
    bottomSpacerHeight: number
}

/**
 * Viewport-based virtualization hook. Instead of creating its own scroll container,
 * it relies on the page/scene scroll and only renders rows that are actually
 * visible in the viewport (plus overscan).
 *
 * Uses `document` scroll capture to detect scrolling from any ancestor,
 * and `getBoundingClientRect()` for viewport-relative positioning. This avoids
 * the need to detect which ancestor is the scroll container.
 */
export function useViewportVirtualization(
    containerRef: RefObject<HTMLElement | null>,
    config: ViewportVirtualizationConfig
): ViewportVirtualizationResult {
    const { rowCount, estimatedRowHeight, overscan = 10, enabled = true } = config

    const [range, setRange] = useState({ start: 0, end: Math.min(overscan * 2, rowCount) })

    const updateRange = useCallback(() => {
        const element = containerRef.current
        if (!element) {
            return
        }

        const elementRect = element.getBoundingClientRect()
        const viewportHeight = window.innerHeight

        // elementRect.top < 0 means we've scrolled past the top of the element
        const scrolledIntoElement = -elementRect.top
        const totalHeight = rowCount * estimatedRowHeight

        // Element is fully below or above the viewport — keep a minimal range
        if (scrolledIntoElement + viewportHeight < 0 || scrolledIntoElement > totalHeight) {
            setRange((prev) => {
                if (prev.start === 0 && prev.end === 0) {
                    return prev
                }
                return { start: 0, end: 0 }
            })
            return
        }

        const visibleStartPx = Math.max(0, scrolledIntoElement)
        const visibleEndPx = Math.max(0, scrolledIntoElement + viewportHeight)

        const rawStart = Math.floor(visibleStartPx / estimatedRowHeight)
        const rawEnd = Math.ceil(visibleEndPx / estimatedRowHeight)

        const start = Math.max(0, rawStart - overscan)
        const end = Math.min(rowCount, rawEnd + overscan)

        setRange((prev) => {
            if (prev.start === start && prev.end === end) {
                return prev
            }
            return { start, end }
        })
    }, [containerRef, rowCount, estimatedRowHeight, overscan])

    useEffect(() => {
        if (!enabled) {
            setRange({ start: 0, end: rowCount })
            return
        }

        let rafId: number | null = null
        const handleScroll = (): void => {
            if (rafId !== null) {
                cancelAnimationFrame(rafId)
            }
            rafId = requestAnimationFrame(updateRange)
        }

        // Capture scroll events from ANY ancestor — scroll events don't bubble,
        // but capture phase works regardless of which element is scrolling
        document.addEventListener('scroll', handleScroll, { capture: true, passive: true })
        window.addEventListener('resize', handleScroll, { passive: true })

        // Initial calculation (delayed to ensure layout is ready)
        rafId = requestAnimationFrame(updateRange)

        return () => {
            document.removeEventListener('scroll', handleScroll, { capture: true })
            window.removeEventListener('resize', handleScroll)
            if (rafId !== null) {
                cancelAnimationFrame(rafId)
            }
        }
    }, [enabled, rowCount, estimatedRowHeight, overscan, updateRange])

    if (!enabled) {
        return { startIndex: 0, endIndex: rowCount, topSpacerHeight: 0, bottomSpacerHeight: 0 }
    }

    return {
        startIndex: range.start,
        endIndex: range.end,
        topSpacerHeight: range.start * estimatedRowHeight,
        bottomSpacerHeight: Math.max(0, (rowCount - range.end) * estimatedRowHeight),
    }
}
