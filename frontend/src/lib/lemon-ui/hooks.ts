import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { useLayoutEffect, useRef, useState } from 'react'

/**
 * Dynamic slider positioning for horizontal single-choice components such as LemonSegmentedButton or LemonTabs.
 * @private
 */
export function useSliderPositioning<C extends HTMLElement, S extends HTMLElement>(
    currentValue: any
): {
    containerRef: React.RefObject<C>
    selectionRef: React.RefObject<S>
    sliderWidth: number
    sliderOffset: number
} {
    const containerRef = useRef<C>(null)
    const selectionRef = useRef<S>(null)
    const [selectionWidth, setSelectionWidth] = useState(0)
    const [selectionOffset, setSelectionOffset] = useState(0)
    const { width: containerWidth } = useResizeObserver({ ref: containerRef })

    useLayoutEffect(() => {
        if (containerRef.current && selectionRef.current) {
            const { left: containerLeft } = containerRef.current.getBoundingClientRect()
            const { width, left: selectedOptionleft } = selectionRef.current.getBoundingClientRect()
            setSelectionWidth(width)
            setSelectionOffset(selectedOptionleft - containerLeft)
        }
    }, [currentValue, containerWidth])

    return {
        containerRef,
        selectionRef,
        sliderWidth: selectionWidth,
        sliderOffset: selectionOffset,
    }
}
