import { RefCallback, RefObject, useMemo, useState } from 'react'
import ResizeObserver from 'resize-observer-polyfill'
import useResizeObserverImport from 'use-resize-observer'

interface ResizeObserverMockType {
    callback: ResizeObserverCallback
    observations: Element[]
    observe: (target: Element) => void
    unobserve: (target: Element) => void
    disconnect: () => void
}

// Use polyfill only if needed
if (!window.ResizeObserver) {
    window.ResizeObserver = ResizeObserver
}

if (window.STORYBOOK) {
    class ResizeObserverMock implements ResizeObserverMockType {
        callback: ResizeObserverCallback
        observations: Element[]

        constructor(callback: ResizeObserverCallback) {
            this.callback = callback
            this.observations = []
        }

        observe(target: Element): void {
            this.observations.push(target)
            this.callback(
                [
                    {
                        target,
                        contentRect: target.getBoundingClientRect(),
                        borderBoxSize: [
                            {
                                blockSize: target.clientHeight,
                                inlineSize: target.clientWidth,
                            },
                        ],
                        contentBoxSize: [
                            {
                                blockSize: target.clientHeight,
                                inlineSize: target.clientWidth,
                            },
                        ],
                        devicePixelContentBoxSize: [
                            {
                                blockSize: target.clientHeight,
                                inlineSize: target.clientWidth,
                            },
                        ],
                    },
                ],
                this
            )
        }

        unobserve(target: Element): void {
            this.observations = this.observations.filter((obs) => obs !== target)
        }

        disconnect(): void {
            this.observations = []
        }
    }

    window.ResizeObserver = ResizeObserverMock
}

export const useResizeObserver = useResizeObserverImport

export function useResizeBreakpoints<T extends string>(
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
        box: 'border-box',
    })

    return { ref: options?.ref || refCb, size }
}
