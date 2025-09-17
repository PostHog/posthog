import { useRef } from 'react'
import useResizeObserver from 'use-resize-observer'

export type TextfitProps = {
    min: number
    max: number
    children: string
}

export const Textfit = ({ min, max, children }: TextfitProps): JSX.Element => {
    const parentRef = useRef<HTMLDivElement>(null)
    const childRef = useRef<HTMLDivElement>(null)
    const fontSizeRef = useRef<number>(min)

    let resizeTimer: NodeJS.Timeout

    const updateFontSize = (size: number): void => {
        fontSizeRef.current = size
        childRef.current!.style.fontSize = `${size}px`
    }

    const handleResize = (): void => {
        clearTimeout(resizeTimer)
        resizeTimer = setTimeout(() => {
            const parent = parentRef.current
            const child = childRef.current

            if (!parent || !child) {
                return
            }

            let mid
            let low = min
            let high = max

            while (low <= high) {
                mid = Math.floor((low + high) / 2)
                updateFontSize(mid)
                const childRect = child.getBoundingClientRect()
                const parentRect = parent.getBoundingClientRect()

                const childFitsParent = childRect.width <= parentRect.width && childRect.height <= parentRect.height

                if (childFitsParent) {
                    low = mid + 1
                } else {
                    high = mid - 1
                }
            }
            mid = Math.min(low, high)

            // Ensure we hit the user-supplied limits
            mid = Math.max(mid, min)
            mid = Math.min(mid, max)

            updateFontSize(mid)
        }, 50)
    }

    useResizeObserver<HTMLDivElement>({
        ref: parentRef,
        onResize: () => handleResize(),
    })

    return (
        <div
            ref={parentRef}
            className="w-full h-full flex items-center justify-center leading-none"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ fontSize: fontSizeRef.current }}
        >
            <div ref={childRef} className="whitespace-nowrap">
                {children}
            </div>
        </div>
    )
}
