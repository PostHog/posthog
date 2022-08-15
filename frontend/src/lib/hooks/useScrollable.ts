import { useCallback, useEffect, useRef, useState } from 'react'
import { useResizeObserver } from './useResizeObserver'

/** Determine whether an element is horizontally scrollable, on the left and on the right respectively. */
export function useScrollable(): [React.RefObject<HTMLDivElement>, string[]] {
    const [isScrollable, setIsScrollable] = useState<[boolean, boolean]>([false, false])
    const scrollRef = useRef<HTMLDivElement>(null)

    const updateIsScrollable = useCallback(() => {
        const element = scrollRef.current
        if (element) {
            const left = element.scrollLeft > 0
            const right =
                element.scrollWidth > element.clientWidth &&
                element.scrollWidth > element.scrollLeft + element.clientWidth
            if (left !== isScrollable[0] || right !== isScrollable[1]) {
                setIsScrollable([left, right])
            }
        }
    }, [isScrollable[0], isScrollable[1]])

    const { width } = useResizeObserver({
        ref: scrollRef,
    })

    useEffect(updateIsScrollable, [updateIsScrollable, width])

    useEffect(() => {
        const element = scrollRef.current
        if (element) {
            element.addEventListener('scroll', updateIsScrollable)
            return () => element.removeEventListener('scroll', updateIsScrollable)
        }
    }, [updateIsScrollable])

    const relevantClassNames: string[] = ['scrollable']
    if (isScrollable[0]) {
        relevantClassNames.push('scrollable--left')
    }
    if (isScrollable[1]) {
        relevantClassNames.push('scrollable--right')
    }

    return [scrollRef, relevantClassNames]
}
