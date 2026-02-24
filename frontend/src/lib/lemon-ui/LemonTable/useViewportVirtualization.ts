import { RefObject, useCallback, useEffect, useRef, useState } from 'react'

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

function getScrollParent(element: HTMLElement): HTMLElement | Window {
    let current: HTMLElement | null = element.parentElement
    while (current) {
        const { overflowY } = getComputedStyle(current)
        if (overflowY === 'auto' || overflowY === 'scroll') {
            return current
        }
        current = current.parentElement
    }
    return window
}

/**
 * Viewport-based virtualization hook. Instead of creating its own scroll container,
 * it relies on the page/scene scroll and only renders rows that are actually
 * visible in the viewport (plus overscan).
 *
 * Works with any scroll ancestor — finds the nearest scrollable parent automatically.
 */
export function useViewportVirtualization(
    containerRef: RefObject<HTMLElement | null>,
    config: ViewportVirtualizationConfig
): ViewportVirtualizationResult {
    const { rowCount, estimatedRowHeight, overscan = 10, enabled = true } = config

    const [range, setRange] = useState({ start: 0, end: Math.min(overscan * 2, rowCount) })
    const scrollParentRef = useRef<HTMLElement | Window | null>(null)

    const updateRange = useCallback(() => {
        const element = containerRef.current
        if (!element) {
            return
        }

        const scrollParent = scrollParentRef.current
        if (!scrollParent) {
            return
        }

        const elementRect = element.getBoundingClientRect()

        let viewportTop: number
        let viewportHeight: number

        if (scrollParent instanceof Window) {
            viewportTop = 0
            viewportHeight = window.innerHeight
        } else {
            const parentRect = scrollParent.getBoundingClientRect()
            viewportTop = parentRect.top
            viewportHeight = parentRect.height
        }

        // How far above the viewport top is the element's top?
        // Positive = element top is above the viewport start (we've scrolled into it)
        const scrolledIntoElement = viewportTop - elementRect.top

        const totalHeight = rowCount * estimatedRowHeight

        if (scrolledIntoElement + viewportHeight < 0 || scrolledIntoElement > totalHeight) {
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
        if (!enabled || !containerRef.current) {
            setRange({ start: 0, end: rowCount })
            return
        }

        scrollParentRef.current = getScrollParent(containerRef.current)
        const scrollParent = scrollParentRef.current

        let rafId: number | null = null
        const handleScroll = (): void => {
            if (rafId !== null) {
                cancelAnimationFrame(rafId)
            }
            rafId = requestAnimationFrame(updateRange)
        }

        const scrollTarget = scrollParent instanceof Window ? window : scrollParent
        scrollTarget.addEventListener('scroll', handleScroll, { passive: true })
        window.addEventListener('resize', handleScroll, { passive: true })

        // Initial calculation
        updateRange()

        return () => {
            scrollTarget.removeEventListener('scroll', handleScroll)
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
