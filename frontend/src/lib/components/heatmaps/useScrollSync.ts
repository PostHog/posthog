import { PostHog } from 'posthog-js'
import { useEffect, useRef } from 'react'

import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'

export function useScrollSync(enabled: boolean = true): {
    innerRef: React.RefObject<HTMLDivElement>
    scrollYRef: React.MutableRefObject<number>
} {
    const innerRef = useRef<HTMLDivElement>(null)
    const scrollYRef = useRef<number>(0)

    useEffect(() => {
        if (!enabled) {
            scrollYRef.current = 0
            return
        }

        let posthogInstance: PostHog | null = null
        try {
            posthogInstance = toolbarConfigLogic.values.posthog
        } catch {
            // toolbarConfigLogic not mounted — fall back to window.scrollY
        }

        let rafId: number | undefined
        let lastScrollY = -1

        const getScrollY = (): number => {
            // Try posthog scroll manager first — it handles pages with custom scroll containers
            try {
                const managed = posthogInstance?.scrollManager?.scrollY()
                if (typeof managed === 'number' && !isNaN(managed)) {
                    return managed
                }
            } catch {
                // scrollManager unavailable or errored
            }
            return document.scrollingElement?.scrollTop ?? window.scrollY ?? 0
        }

        const applyScroll = (): void => {
            const scrollY = getScrollY()
            if (scrollY !== lastScrollY) {
                lastScrollY = scrollY
                scrollYRef.current = scrollY
                const inner = innerRef.current
                if (inner) {
                    inner.style.transform = `translateY(${-scrollY}px)`
                }
            }
        }

        const onFrame = (): void => {
            applyScroll()
            rafId = requestAnimationFrame(onFrame)
        }

        rafId = requestAnimationFrame(onFrame)

        // Also listen for scroll events for immediate response.
        // Capture phase catches events from nested scrollable containers too.
        const onScroll = (): void => applyScroll()
        document.addEventListener('scroll', onScroll, true)

        return () => {
            if (rafId !== undefined) {
                cancelAnimationFrame(rafId)
            }
            document.removeEventListener('scroll', onScroll, true)
        }
    }, [enabled])

    return { innerRef, scrollYRef }
}
