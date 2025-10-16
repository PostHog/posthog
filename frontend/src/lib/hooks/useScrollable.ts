import { useLayoutEffect, useRef, useState } from 'react'

import { useResizeObserver } from './useResizeObserver'

type ScrollableDirections = {
    isScrollableLeft: boolean
    isScrollableRight: boolean
    isScrollableTop: boolean
    isScrollableBottom: boolean
}

/** Determine whether an element is horizontally scrollable, on the left and on the right respectively. */
export function useScrollable(): { ref: React.MutableRefObject<HTMLDivElement | null> } & ScrollableDirections {
    const [isScrollable, setIsScrollable] = useState<ScrollableDirections>({
        isScrollableLeft: false,
        isScrollableRight: false,
        isScrollableTop: false,
        isScrollableBottom: false,
    })

    // We use a ref to simplify the reference to the current value of isScrollable
    const isScrollableRef = useRef(isScrollable)
    isScrollableRef.current = isScrollable

    const scrollRef = useRef<HTMLDivElement | null>(null)

    const { width, height } = useResizeObserver({
        ref: scrollRef,
    })

    function updateIsScrollable(element: HTMLElement): void {
        const newScrollable = {
            isScrollableLeft: element.scrollLeft > 0,
            isScrollableTop: element.scrollTop > 0,
            isScrollableRight: Math.floor(element.scrollWidth) > Math.ceil(element.scrollLeft + element.clientWidth),
            isScrollableBottom: Math.floor(element.scrollHeight) > Math.ceil(element.scrollTop + element.clientHeight),
        }

        const hasChanged = Object.keys(newScrollable).some((key) => newScrollable[key] !== isScrollableRef.current[key])

        if (hasChanged) {
            setIsScrollable(newScrollable)
        }
    }

    useLayoutEffect(() => {
        // oxlint-disable-next-line @typescript-eslint/no-unused-vars
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
                clearTimeout(timeout)
            }
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    useLayoutEffect(() => {
        const element = scrollRef.current
        if (element) {
            updateIsScrollable(element)
        }
    }, [width, height])

    return {
        ...isScrollable,
        ref: scrollRef,
    }
}
