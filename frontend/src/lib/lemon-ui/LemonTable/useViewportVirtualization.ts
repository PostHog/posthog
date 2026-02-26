import { RefObject, useCallback, useEffect, useRef, useState } from 'react'

export interface ViewportVirtualizationConfig {
    /** Total number of rows to virtualize */
    rowCount: number
    /** Estimated height of each row in pixels. Used as fallback for rows not yet measured. */
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
 * Viewport-based virtualization hook with dynamic row height support.
 *
 * Rendered rows must have a `data-virtualized-index` attribute set to their
 * row index. The hook measures these elements via `getBoundingClientRect()`
 * and caches per-row heights for accurate spacer and range calculations.
 * Unmeasured rows use `estimatedRowHeight` as a fallback.
 *
 * Uses `document` scroll capture to detect scrolling from any ancestor,
 * and `getBoundingClientRect()` for viewport-relative positioning.
 */
export function useViewportVirtualization(
    containerRef: RefObject<HTMLElement | null>,
    config: ViewportVirtualizationConfig
): ViewportVirtualizationResult {
    const { rowCount, estimatedRowHeight, overscan = 10, enabled = true } = config

    const heightCacheRef = useRef(new Map<number, number>())

    const [state, setState] = useState(() => {
        const initialEnd = Math.min(overscan * 2, rowCount)
        return {
            start: 0,
            end: initialEnd,
            topSpacerHeight: 0,
            bottomSpacerHeight: estimatedRowHeight * Math.max(0, rowCount - initialEnd),
        }
    })

    const measureChildren = useCallback(() => {
        const container = containerRef.current
        if (!container) {
            return
        }

        const elements = Array.from(container.querySelectorAll('[data-virtualized-index]'))
        for (let i = 0; i < elements.length; i++) {
            const el = elements[i] as HTMLElement
            const idx = parseInt(el.dataset.virtualizedIndex!, 10)
            if (isNaN(idx)) {
                continue
            }

            let height: number
            if (i < elements.length - 1) {
                // Use distance to the next indexed element — this naturally includes
                // any expansion rows or extra DOM between logical rows
                const nextEl = elements[i + 1] as HTMLElement
                height = nextEl.getBoundingClientRect().top - el.getBoundingClientRect().top
            } else {
                // Last visible row: measure from its top through all subsequent
                // non-indexed siblings (e.g. expansion rows in LemonTable)
                height = el.getBoundingClientRect().height
                let sibling = el.nextElementSibling
                while (
                    sibling &&
                    !sibling.hasAttribute('data-virtualized-index') &&
                    !sibling.hasAttribute('aria-hidden')
                ) {
                    height += (sibling as HTMLElement).getBoundingClientRect().height
                    sibling = sibling.nextElementSibling
                }
            }

            if (height > 0) {
                heightCacheRef.current.set(idx, Math.round(height))
            }
        }
    }, [containerRef])

    const updateRange = useCallback(() => {
        const element = containerRef.current
        if (!element) {
            return
        }

        measureChildren()

        const elementRect = element.getBoundingClientRect()
        const viewportHeight = window.innerHeight
        const scrolledIntoElement = -elementRect.top

        // Calculate total height using cached measurements
        let totalHeight = 0
        for (let i = 0; i < rowCount; i++) {
            totalHeight += heightCacheRef.current.get(i) ?? estimatedRowHeight
        }

        if (scrolledIntoElement + viewportHeight < 0 || scrolledIntoElement > totalHeight) {
            setState((prev) => {
                if (prev.start === 0 && prev.end === 0) {
                    return prev
                }
                return { start: 0, end: 0, topSpacerHeight: 0, bottomSpacerHeight: totalHeight }
            })
            return
        }

        const visibleStart = Math.max(0, scrolledIntoElement)
        const visibleEnd = Math.max(0, scrolledIntoElement + viewportHeight)

        // Find the first row whose bottom edge enters the visible area
        let cumH = 0
        let rawStart = 0
        for (let i = 0; i < rowCount; i++) {
            const rowH = heightCacheRef.current.get(i) ?? estimatedRowHeight
            if (cumH + rowH > visibleStart) {
                rawStart = i
                break
            }
            cumH += rowH
            if (i === rowCount - 1) {
                rawStart = rowCount
            }
        }

        // Find the first row whose top edge is past the visible area
        let rawEnd = rowCount
        cumH = 0
        for (let i = 0; i < rowCount; i++) {
            cumH += heightCacheRef.current.get(i) ?? estimatedRowHeight
            if (cumH >= visibleEnd) {
                rawEnd = i + 1
                break
            }
        }

        const start = Math.max(0, rawStart - overscan)
        const end = Math.min(rowCount, rawEnd + overscan)

        // Calculate spacer heights from cached measurements
        let topSpacer = 0
        for (let i = 0; i < start; i++) {
            topSpacer += heightCacheRef.current.get(i) ?? estimatedRowHeight
        }

        let renderedH = 0
        for (let i = start; i < end; i++) {
            renderedH += heightCacheRef.current.get(i) ?? estimatedRowHeight
        }

        const bottomSpacer = Math.max(0, totalHeight - topSpacer - renderedH)

        setState((prev) => {
            if (
                prev.start === start &&
                prev.end === end &&
                prev.topSpacerHeight === topSpacer &&
                prev.bottomSpacerHeight === bottomSpacer
            ) {
                return prev
            }
            return { start, end, topSpacerHeight: topSpacer, bottomSpacerHeight: bottomSpacer }
        })
    }, [containerRef, rowCount, estimatedRowHeight, overscan, measureChildren])

    // Scroll + resize listeners
    useEffect(() => {
        if (!enabled) {
            setState({ start: 0, end: rowCount, topSpacerHeight: 0, bottomSpacerHeight: 0 })
            return
        }

        let rafId: number | null = null
        const handleScroll = (): void => {
            if (rafId !== null) {
                cancelAnimationFrame(rafId)
            }
            rafId = requestAnimationFrame(updateRange)
        }

        document.addEventListener('scroll', handleScroll, { capture: true, passive: true })
        window.addEventListener('resize', handleScroll, { passive: true })

        rafId = requestAnimationFrame(updateRange)

        return () => {
            document.removeEventListener('scroll', handleScroll, { capture: true })
            window.removeEventListener('resize', handleScroll)
            if (rafId !== null) {
                cancelAnimationFrame(rafId)
            }
        }
    }, [enabled, rowCount, updateRange])

    // Re-measure after React renders new rows (range changed → new DOM elements)
    useEffect(() => {
        if (!enabled) {
            return
        }
        const rafId = requestAnimationFrame(updateRange)
        return () => cancelAnimationFrame(rafId)
    }, [state.start, state.end, enabled, updateRange])

    if (!enabled) {
        return { startIndex: 0, endIndex: rowCount, topSpacerHeight: 0, bottomSpacerHeight: 0 }
    }

    return {
        startIndex: state.start,
        endIndex: state.end,
        topSpacerHeight: state.topSpacerHeight,
        bottomSpacerHeight: state.bottomSpacerHeight,
    }
}
