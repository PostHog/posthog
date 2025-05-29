import { useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { getScrollableContainer } from '../maxLogic'
import { maxThreadLogic } from '../maxThreadLogic'

export function ThreadAutoScroller({ children }: { children: React.ReactNode }): JSX.Element {
    const { streamingActive, threadGrouped } = useValues(maxThreadLogic)

    const scrollOrigin = useRef({ user: false, programmatic: true })
    const sentinelRef = useRef<HTMLDivElement | null>(null)

    const scrollToBottom = useRef(() => {
        if (!sentinelRef.current) {
            return
        }

        // Get the root scrollable element
        const scrollableContainer = getScrollableContainer(sentinelRef.current)

        if (scrollableContainer && !scrollOrigin.current.user) {
            // Lock the scroll listener, so we don't detect the programmatic scroll as a user scroll
            scrollOrigin.current.programmatic = true
            scrollableContainer.scrollTo({ top: scrollableContainer.scrollHeight })
            // Reset the scroll when we're done
            requestAnimationFrame(() => {
                scrollOrigin.current.programmatic = false
            })
        }
    }).current // Keep the stable reference

    useEffect(() => {
        const scrollableContainer = getScrollableContainer(sentinelRef.current)
        if (!sentinelRef.current || !streamingActive || !scrollableContainer) {
            return
        }

        // Detect if the user has scrolled the content during generation,
        // so we can stop auto-scrolling
        function scrollListener(): void {
            if (scrollOrigin.current.programmatic) {
                return
            }
            scrollOrigin.current.user = true
        }
        scrollableContainer.addEventListener('scroll', scrollListener)

        // When the thread is resized during generation, we need to scroll to the bottom
        // eslint-disable-next-line compat/compat
        const resizeObserver = new ResizeObserver(() => {
            scrollToBottom()
        })
        resizeObserver.observe(sentinelRef.current)

        return () => {
            resizeObserver.disconnect()
            scrollableContainer.removeEventListener('scroll', scrollListener)
            scrollOrigin.current = { user: false, programmatic: false }
        }
    }, [streamingActive, scrollToBottom])

    useEffect(() => {
        if (!streamingActive) {
            return
        }
        scrollToBottom()
    }, [streamingActive, scrollToBottom, threadGrouped]) // Scroll when the thread updates

    return (
        <>
            {children}
            <div id="max-sentinel" className="pointer-events-none h-0" ref={sentinelRef} />
        </>
    )
}
