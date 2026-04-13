import { useCallback, useRef } from 'react'

const DEFAULT_THRESHOLD_PX = 100

export type ScrollObserverOptions = {
    onScrollTop?: () => void
    onScrollBottom?: () => void
    /** Pixel distance from edge to trigger callbacks (default: 100) */
    thresholdPx?: number
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
                onScrollTop?.()
            } else if (scrollTop + clientHeight >= scrollHeight - thresholdPx) {
                onScrollBottom?.()
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
