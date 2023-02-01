import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useResizeObserver } from './useResizeObserver'

/** Determine whether an element is horizontally scrollable, on the left and on the right respectively. */
export function useScrollable(): [React.RefObject<HTMLDivElement>, string[]] {
    const [isScrollable, setIsScrollable] = useState<[boolean, boolean]>([false, false])
    const scrollRef = useRef<HTMLDivElement>(null)

    const { width } = useResizeObserver({
        ref: scrollRef,
    })

    function updateIsScrollable(element: HTMLElement): void {
        const left = element.scrollLeft > 0
        const right = element.scrollWidth > element.scrollLeft + element.clientWidth
        setIsScrollable([left, right])
    }

    useEffect(() => {
        // eslint-disable-next-line @typescript-eslint/no-unused-vars
        function handler(this: HTMLElement, _: Event): void {
            updateIsScrollable(this)
        }
        const element = scrollRef.current
        if (element) {
            element.addEventListener('scroll', handler)
            // For some reason scrollWidth is not accurate until hundreds of milliseconds after the element is rendered,
            // and there's no observer or listener for scrollWidth/scrollHeight - so we need to check with a delay
            const timeout = setTimeout(() => updateIsScrollable(element), 200)
            return () => {
                element.removeEventListener('scroll', handler)
                clearInterval(timeout)
            }
        }
    }, [scrollRef.current])

    useLayoutEffect(() => {
        const element = scrollRef.current
        if (element) {
            updateIsScrollable(element)
        }
    }, [width])

    const relevantClassNames: string[] = ['scrollable']
    if (isScrollable[0]) {
        relevantClassNames.push('scrollable--left')
    }
    if (isScrollable[1]) {
        relevantClassNames.push('scrollable--right')
    }

    return [scrollRef, relevantClassNames]
}
