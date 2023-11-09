import { RefCallback, RefObject, useMemo, useState } from 'react'
import ResizeObserver from 'resize-observer-polyfill'
import useResizeObserverImport from 'use-resize-observer'

// Use polyfill only if needed
if (!window.ResizeObserver) {
    window.ResizeObserver = ResizeObserver
}

export const useResizeObserver = useResizeObserverImport

export function useResizeBreakpoints<T>(
    breakpoints: { [key: number]: T },
    options?: {
        ref?: RefObject<HTMLDivElement> | null | undefined
        initialSize?: T
    }
): {
    ref?: RefCallback<HTMLDivElement> | RefObject<HTMLDivElement>
    size: T
} {
    const sortedKeys: number[] = useMemo(
        () =>
            Object.keys(breakpoints)
                .map((x) => parseInt(x, 10))
                .sort((a, b) => a - b),
        [breakpoints]
    )
    const [size, setSize] = useState(options?.initialSize ?? breakpoints[sortedKeys[0]])

    const { ref: refCb } = useResizeObserver<HTMLDivElement>({
        ref: options?.ref,
        onResize: ({ width = 1 }) => {
            let newSize = breakpoints[sortedKeys[0]]

            for (const key of sortedKeys) {
                if (width > key) {
                    newSize = breakpoints[key]
                }
            }
            if (newSize != size) {
                setSize(newSize)
            }
        },
    })

    return { ref: options?.ref || refCb, size }
}
