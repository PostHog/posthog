import { RefObject, useLayoutEffect, useRef } from 'react'

export function useHoldTallestHeight(
    containerRef: RefObject<HTMLElement>,
    contentRef: RefObject<HTMLElement>,
    enabled: boolean
): void {
    const tallestRef = useRef(0)

    useLayoutEffect(() => {
        const container = containerRef.current
        const content = contentRef.current
        if (!container || !content) {
            return
        }
        if (!enabled) {
            tallestRef.current = 0
            container.style.removeProperty('min-height')
            return
        }
        const holdTallest = (): void => {
            tallestRef.current = Math.max(tallestRef.current, content.getBoundingClientRect().height)
            container.style.minHeight = `${tallestRef.current}px`
        }
        holdTallest()
        const observer = new ResizeObserver(holdTallest)
        observer.observe(content)
        return () => observer.disconnect()
    }, [containerRef, contentRef, enabled])
}
