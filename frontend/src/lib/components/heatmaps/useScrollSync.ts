import { useEffect, useRef } from 'react'

import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'

/**
 * Provides scroll-synced positioning for heatmap overlays.
 *
 * In 'absolute' mode, polls posthog.scrollManager.scrollY() via rAF to
 * track scroll position — even on sites with custom scroll containers
 * where window.scrollY stays 0. Updates the element's CSS transform
 * directly for compositor-only animation (no React re-renders).
 *
 * In 'fixed' mode, the overlay fills the viewport and needs no scroll sync.
 *
 * We access toolbarConfigLogic.values.posthog directly rather than via
 * useValues/connect. This is intentional: toolbarConfigLogic is only
 * mounted in the toolbar context, and we need the instance reference
 * for rAF polling — not reactivity. The try-catch handles the in-app
 * context where this logic isn't mounted. The posthog instance never
 * changes after initialization.
 */
export function useScrollSync(enabled: boolean = true): {
    innerRef: React.RefObject<HTMLDivElement>
    scrollYRef: React.MutableRefObject<number>
} {
    const innerRef = useRef<HTMLDivElement>(null) as React.RefObject<HTMLDivElement>
    const scrollYRef = useRef<number>(0)

    useEffect(() => {
        if (!enabled) {
            scrollYRef.current = 0
            return
        }

        let posthogInstance: any = null
        try {
            posthogInstance = toolbarConfigLogic.values.posthog
        } catch {
            // toolbarConfigLogic not mounted (in-app context) — fall back to window.scrollY
        }

        let rafId: number
        let lastScrollY = -1

        const onFrame = (): void => {
            const scrollY = posthogInstance?.scrollManager?.scrollY() ?? window.scrollY
            if (scrollY !== lastScrollY) {
                lastScrollY = scrollY
                scrollYRef.current = scrollY
                const inner = innerRef.current
                if (inner) {
                    inner.style.transform = `translateY(${-scrollY}px)`
                }
            }
            rafId = requestAnimationFrame(onFrame)
        }

        rafId = requestAnimationFrame(onFrame)

        return () => cancelAnimationFrame(rafId)
    }, [enabled])

    return { innerRef, scrollYRef }
}
