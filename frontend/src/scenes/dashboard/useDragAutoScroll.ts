import { useCallback, useEffect, useRef } from 'react'

const DRAG_AUTO_SCROLL_THRESHOLD = 100
const DRAG_AUTO_SCROLL_SPEED = 50

export interface DragAutoScroll {
    startAutoScroll: () => void
    autoScrollOnDrag: (event: Event) => void
    stopAutoScroll: () => void
}

/** Scrolls `#main-content` while a dragged tile is near its top or bottom edge. */
export function useDragAutoScroll(): DragAutoScroll {
    const scrollContainerRef = useRef<HTMLElement | null>(null)
    const scrollContainerRectRef = useRef<DOMRect | null>(null)
    const scrollAnimationRef = useRef<number | null>(null)

    const cancelScroll = useCallback((): void => {
        if (scrollAnimationRef.current) {
            cancelAnimationFrame(scrollAnimationRef.current)
            scrollAnimationRef.current = null
        }
    }, [])

    const stopAutoScroll = useCallback((): void => {
        cancelScroll()
        scrollContainerRef.current = null
        scrollContainerRectRef.current = null
    }, [cancelScroll])

    useEffect(() => stopAutoScroll, [stopAutoScroll])

    const startAutoScroll = useCallback((): void => {
        scrollContainerRef.current = document.getElementById('main-content')
        scrollContainerRectRef.current = scrollContainerRef.current?.getBoundingClientRect() ?? null
    }, [])

    const autoScrollOnDrag = useCallback(
        (event: Event): void => {
            cancelScroll()

            const scrollContainer = scrollContainerRef.current
            const containerRect = scrollContainerRectRef.current
            if (!scrollContainer || !containerRect) {
                return
            }

            const mouseY = (event as MouseEvent).clientY

            let scrollSpeed = 0
            if (mouseY < containerRect.top + DRAG_AUTO_SCROLL_THRESHOLD) {
                scrollSpeed = -DRAG_AUTO_SCROLL_SPEED
            } else if (mouseY > containerRect.bottom - DRAG_AUTO_SCROLL_THRESHOLD) {
                scrollSpeed = DRAG_AUTO_SCROLL_SPEED
            }

            if (scrollSpeed !== 0) {
                const scroll = (): void => {
                    const atTop = scrollSpeed < 0 && scrollContainer.scrollTop === 0
                    const atBottom =
                        scrollSpeed > 0 &&
                        scrollContainer.scrollTop + scrollContainer.clientHeight >= scrollContainer.scrollHeight
                    if (atTop || atBottom) {
                        return
                    }
                    scrollContainer.scrollBy(0, scrollSpeed)
                    scrollAnimationRef.current = requestAnimationFrame(scroll)
                }
                scrollAnimationRef.current = requestAnimationFrame(scroll)
            }
        },
        [cancelScroll]
    )

    return { startAutoScroll, autoScrollOnDrag, stopAutoScroll }
}
