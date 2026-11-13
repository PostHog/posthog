import { useLayoutEffect, useRef, useState } from 'react'

import { useResizeObserver } from 'lib/hooks/useResizeObserver'

/**
 * Dynamic slider positioning for horizontal single-choice components such as LemonSegmentedButton or LemonTabs.
 * @private
 */
export function useSliderPositioning<C extends HTMLElement, S extends HTMLElement>(
    currentValue: React.Key | null | undefined,
    transitionMs: number,
    /** Changes when the options change, so the slider follows a selection that moved without changing. */
    layoutKey?: string,
    /** Moves the slider when an option's width changes, as when a tab label is renamed in place. */
    trackOptionSizes = false
): {
    containerRef: React.RefObject<C>
    selectionRef: React.RefObject<S>
    sliderWidth: number
    sliderOffset: number
    transitioning: boolean
} {
    const hasRenderedInitiallyRef = useRef(false)
    const containerRef = useRef<C>(null)
    const selectionRef = useRef<S>(null)
    const [[selectionWidth, selectionOffset], setSelectionWidthAndOffset] = useState<[number, number]>([0, 0])
    const [transitioning, setTransitioning] = useState(false)
    const { width: containerWidth = 0 } = useResizeObserver({ ref: containerRef })

    useLayoutEffect(() => {
        if (selectionRef.current) {
            setSelectionWidthAndOffset([selectionRef.current.offsetWidth, selectionRef.current.offsetLeft])
            if (hasRenderedInitiallyRef.current) {
                setTransitioning(true)
                const transitioningTimeout = setTimeout(() => setTransitioning(false), transitionMs)
                return () => clearTimeout(transitioningTimeout)
            }
            hasRenderedInitiallyRef.current = true
        }
    }, [currentValue, containerWidth, layoutKey]) // oxlint-disable-line react-hooks/exhaustive-deps

    // An option whose label changes width moves the selection without changing the container's width.
    useLayoutEffect(() => {
        const container = containerRef.current
        if (!trackOptionSizes || !container) {
            return
        }
        const observer = new ResizeObserver(() => {
            const selection = selectionRef.current
            if (selection) {
                const next: [number, number] = [selection.offsetWidth, selection.offsetLeft]
                setSelectionWidthAndOffset((current) =>
                    current[0] === next[0] && current[1] === next[1] ? current : next
                )
            }
        })
        Array.from(container.children).forEach((option) => observer.observe(option))
        return () => observer.disconnect()
    }, [currentValue, layoutKey, trackOptionSizes])

    return {
        containerRef,
        selectionRef,
        sliderWidth: selectionWidth,
        sliderOffset: selectionOffset,
        transitioning,
    }
}
