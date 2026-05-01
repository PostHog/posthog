import { useCallback, useRef } from 'react'

const DEFAULT_THRESHOLD_PX = 100

export type ScrollObserverOptions = {
    onScrollTop?: () => void | Promise<void>
    onScrollBottom?: () => void | Promise<void>
    /** Pixel distance from edge to trigger callbacks (default: 100) */
    thresholdPx?: number
}

function invokeObserverCallback(callback?: () => void | Promise<void>): void {
    if (!callback) {
        return
    }

    try {
        const maybePromise = callback()
        if (maybePromise instanceof Promise) {
            void maybePromise.catch(() => undefined)
        }
    } catch {
        // Prevent scroll callbacks from breaking the observer.
    }
}

export function useScrollObserver({
    onScrollTop,
    onScrollBottom,
    thresholdPx = DEFAULT_THRESHOLD_PX,
}: ScrollObserverOptions = {}): (el: HTMLDivElement | null) => void {
    const containerRef = useRef<HTMLDivElement | null>(null)

    const handleScroll = useCallback(
        (evt: Event) => {
            const target = evt.target as HTMLElement
            if (!target) {
                return
            }
            const { scrollTop, scrollHeight, clientHeight } = target

            if (scrollTop <= thresholdPx) {
                invokeObserverCallback(onScrollTop)
            } else if (scrollTop + clientHeight >= scrollHeight - thresholdPx) {
                invokeObserverCallback(onScrollBottom)
            }
        },
        [onScrollTop, onScrollBottom, thresholdPx]
    )

    return useCallback(
        (el: HTMLDivElement | null) => {
            const previousEl = containerRef.current

            if (previousEl && previousEl !== el) {
                previousEl.removeEventListener('scroll', handleScroll)
            }

            if (!el) {
                containerRef.current = null
                return
            }

            if (previousEl === el) {
                return
            }

            containerRef.current = el
            el.addEventListener('scroll', handleScroll, { passive: true })
        },
        [handleScroll]
    )
}
