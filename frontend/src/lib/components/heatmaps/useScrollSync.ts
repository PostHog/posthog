import { PostHog } from 'posthog-js'
import { useEffect, useRef } from 'react'

import { getToolbarRuntime } from 'lib/toolbar/toolbarRuntime'

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

        const posthogInstance: PostHog | null = getToolbarRuntime()?.posthog() ?? null

        let rafId: number | undefined
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

        return () => {
            if (rafId !== undefined) {
                cancelAnimationFrame(rafId)
            }
        }
    }, [enabled])

    return { innerRef, scrollYRef }
}
