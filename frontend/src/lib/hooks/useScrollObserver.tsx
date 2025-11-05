import { useCallback, useRef } from 'react'

export type ScrollObserverOptions = {
    onScrollTop?: () => void
    onScrollBottom?: () => void
}

export function useScrollObserver({ onScrollTop, onScrollBottom }: ScrollObserverOptions = {}): (
    el: HTMLDivElement | null
) => void {
    const containerRef = useRef<HTMLDivElement | null>(null)

    const handleScroll = useCallback(
        (evt: Event) => {
            const target = evt.target as HTMLElement
            if (!target) {
                return
            }
            const scrollTop = target.scrollTop
            const scrollHeight = target.scrollHeight
            const clientHeight = target.clientHeight

            if (scrollHeight === clientHeight) {
                return
            }

            const scrollRatio = scrollTop / (scrollHeight - clientHeight)

            if (scrollRatio <= 0) {
                return onScrollTop?.()
            }

            if (scrollRatio >= 1) {
                return onScrollBottom?.()
            }
        },
        [onScrollTop, onScrollBottom]
    )

    return useCallback(
        (el: HTMLDivElement | null) => {
            if (!el) {
                if (containerRef.current) {
                    containerRef.current.removeEventListener('scroll', handleScroll)
                }
            } else {
                containerRef.current = el
                el.addEventListener('scroll', handleScroll)
            }
        },
        [handleScroll]
    )
}
