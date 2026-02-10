import { useLayoutEffect, useRef } from 'react'
import useResizeObserver from 'use-resize-observer'

export type TextfitProps = {
    min: number
    max: number
    children: string
}

export const Textfit = ({ min, max, children }: TextfitProps): JSX.Element => {
    const parentRef = useRef<HTMLDivElement>(null)
    const childRef = useRef<HTMLDivElement>(null)

    const calculateFontSize = (): void => {
        const parent = parentRef.current
        const child = childRef.current

        if (!parent || !child) {
            return
        }

        let low = min
        let high = max

        while (low <= high) {
            const mid = Math.floor((low + high) / 2)
            child.style.fontSize = `${mid}px`

            const childFitsParent =
                child.getBoundingClientRect().width <= parent.getBoundingClientRect().width &&
                child.getBoundingClientRect().height <= parent.getBoundingClientRect().height

            if (childFitsParent) {
                low = mid + 1
            } else {
                high = mid - 1
            }
        }

        const finalSize = Math.max(min, Math.min(max, Math.min(low, high)))
        child.style.fontSize = `${finalSize}px`
    }

    useLayoutEffect(() => {
        calculateFontSize()
    }, [children, min, max])

    useResizeObserver<HTMLDivElement>({
        ref: parentRef,
        onResize: calculateFontSize,
    })

    return (
        <div ref={parentRef} className="w-full h-full flex items-center justify-center leading-none">
            <div ref={childRef} className="whitespace-nowrap">
                {children}
            </div>
        </div>
    )
}
