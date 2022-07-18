import { useCallback, useEffect, useRef, useState } from 'react'
import { useResizeObserver } from './useResizeObserver'

/** Determine whether an element is horizontally scrollable, on the left and on the right respectively. */
export function useScrollable(): [
    React.RefObject<HTMLDivElement>,
    string[],
    {
        top: boolean
        bottom: boolean
        left: boolean
        right: boolean
    }
] {
    const [isScrollableX, setIsScrollableX] = useState<[boolean, boolean]>([false, false])
    const [isScrollableY, setIsScrollableY] = useState<[boolean, boolean]>([false, false])
    const scrollRef = useRef<HTMLDivElement>(null)

    const updateIsScrollableX = useCallback(() => {
        const element = scrollRef.current
        if (element) {
            const left = element.scrollLeft > 0
            const right =
                element.scrollWidth > element.clientWidth &&
                element.scrollWidth > element.scrollLeft + element.clientWidth
            element.scrollHeight > element.scrollTop + element.clientHeight
            if (left !== isScrollableX[0] || right !== isScrollableX[1]) {
                setIsScrollableX([left, right])
            }
        }
    }, [isScrollableX[0], isScrollableX[1]])

    const updateIsScrollableY = useCallback(() => {
        const element = scrollRef.current
        if (element) {
            const top = element.scrollTop > 0
            const bottom =
                element.scrollHeight > element.clientHeight &&
                element.scrollHeight > element.scrollTop + element.clientHeight
            if (top !== isScrollableY[0] || bottom !== isScrollableY[1]) {
                setIsScrollableY([top, bottom])
            }
        }
    }, [isScrollableY[0], isScrollableY[1]])

    const { width, height } = useResizeObserver({
        ref: scrollRef,
    })

    useEffect(updateIsScrollableX, [updateIsScrollableX, width])
    useEffect(updateIsScrollableY, [updateIsScrollableY, height])

    useEffect(() => {
        const element = scrollRef.current
        if (element) {
            element.addEventListener('scroll', updateIsScrollableX)
            element.addEventListener('scroll', updateIsScrollableY)
            return () => {
                element.removeEventListener('scroll', updateIsScrollableX)
                element.removeEventListener('scroll', updateIsScrollableY)
            }
        }
    }, [updateIsScrollableX, updateIsScrollableY])

    const relevantClassNames: string[] = ['scrollable']
    if (isScrollableX[0]) {
        relevantClassNames.push('scrollable--left')
    }
    if (isScrollableX[1]) {
        relevantClassNames.push('scrollable--right')
    }

    return [
        scrollRef,
        relevantClassNames,
        { top: isScrollableY[0], bottom: isScrollableY[1], left: isScrollableX[0], right: isScrollableX[1] },
    ]
}
