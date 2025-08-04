import { useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { getScrollableContainer } from '../maxLogic'
import { maxThreadLogic } from '../maxThreadLogic'

export function ThreadAutoScroller({ children }: { children: React.ReactNode }): JSX.Element {
    const { streamingActive, threadGrouped, conversation } = useValues(maxThreadLogic)

    const scrollOrigin = useRef({ user: false, programmatic: false, resizing: false })
    const sentinelRef = useRef<HTMLDivElement | null>(null)

    const scrollToBottom = useRef(() => {
        if (!sentinelRef.current) {
            return
        }

        // Get the root scrollable element
        const scrollableContainer = getScrollableContainer(sentinelRef.current)

        if (scrollableContainer) {
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
        function scrollListener(event: Event): void {
            if (
                scrollOrigin.current.programmatic ||
                scrollOrigin.current.resizing ||
                !sentinelRef.current ||
                !event.target
            ) {
                return
            }

            const scrollableContainer = event.target as HTMLElement
            // Can be tracked through the IntersectionObserver, but the intersection observer event is fired after the scroll event,
            // so it adds an annoying delay.
            const isAtBottom =
                sentinelRef.current.getBoundingClientRect().top <= scrollableContainer.getBoundingClientRect().bottom

            if (!isAtBottom) {
                scrollOrigin.current.user = true
            }
        }
        scrollableContainer.addEventListener('scroll', scrollListener)

        // When the thread is resized during generation, we need to scroll to the bottom
        let resizeTimeout: NodeJS.Timeout | null = null
        // eslint-disable-next-line compat/compat
        const resizeObserver = new ResizeObserver(() => {
            if (scrollOrigin.current.user) {
                return
            }

            if (resizeTimeout) {
                clearTimeout(resizeTimeout)
                resizeTimeout = null
            }

            scrollOrigin.current.resizing = true
            scrollToBottom()
            // Block the scroll listener from firing
            resizeTimeout = setTimeout(() => {
                scrollOrigin.current.resizing = false
                resizeTimeout = null
            }, 50)
        })
        resizeObserver.observe(sentinelRef.current)

        // Reset the user interaction if we've reached the bottom of the screen
        // eslint-disable-next-line compat/compat
        const intersectionObserver = new IntersectionObserver(([entries]) => {
            if (!scrollOrigin.current.programmatic && scrollOrigin.current.user && entries.isIntersecting) {
                scrollOrigin.current.user = false
            }
        })
        intersectionObserver.observe(sentinelRef.current)

        return () => {
            resizeObserver.disconnect()
            intersectionObserver.disconnect()
            scrollableContainer.removeEventListener('scroll', scrollListener)
            scrollOrigin.current = { user: false, programmatic: false, resizing: false }
            if (resizeTimeout) {
                clearTimeout(resizeTimeout)
            }
        }
    }, [streamingActive, scrollToBottom])

    useEffect(() => {
        if (!streamingActive || scrollOrigin.current.user) {
            return
        }
        scrollToBottom()
    }, [streamingActive, scrollToBottom, threadGrouped]) // Scroll when the thread updates

    // Scroll to bottom when a new thread becomes visible
    useEffect(() => {
        if (!conversation || scrollOrigin.current.user) {
            return
        }
        // Use a small delay to ensure the thread content is rendered
        const timer = setTimeout(() => {
            scrollToBottom()
        }, 100)
        return () => clearTimeout(timer)
    }, [conversation?.id, scrollToBottom]) // Scroll when conversation changes

    return (
        <>
            {children}
            <div id="max-sentinel" className="pointer-events-none h-0" ref={sentinelRef} />
        </>
    )
}
