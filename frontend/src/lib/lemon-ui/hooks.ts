import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { useLayoutEffect, useRef, useState } from 'react'

/**
 * Dynamic slider positioning for horizontal single-choice components such as LemonSegmentedButton or LemonTabs.
 * @private
 */
export function useSliderPositioning<C extends HTMLElement, S extends HTMLElement>(
    currentValue: React.Key | null | undefined,
    transitionMs: number
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
    const { width: containerWidth } = useResizeObserver({ ref: containerRef })

    useLayoutEffect(() => {
        if (containerRef.current && selectionRef.current) {
            const { left: containerLeft } = containerRef.current.getBoundingClientRect()
            const { width, left: selectedOptionleft } = selectionRef.current.getBoundingClientRect()
            setSelectionWidthAndOffset([width, selectedOptionleft - containerLeft])
            if (hasRenderedInitiallyRef.current) {
                setTransitioning(true)
                const transitioningTimeout = setTimeout(() => setTransitioning(false), transitionMs)
                return () => clearTimeout(transitioningTimeout)
            } else {
                hasRenderedInitiallyRef.current = true
            }
        }
    }, [currentValue, containerWidth])

    return {
        containerRef,
        selectionRef,
        sliderWidth: selectionWidth,
        sliderOffset: selectionOffset,
        transitioning,
    }
}
