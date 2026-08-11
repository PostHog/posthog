import { useEffect, useRef } from 'react'
import { annotate } from 'rough-notation'
import type { RoughAnnotation } from 'rough-notation/lib/model'

/**
 * Minimal port of posthog.com's RoughAnnotation wrapper (src/components/Code/RoughAnnotation.tsx)
 * for the hand-drawn highlight/squiggle treatments of the site's visual language. Draws on mount -
 * onboarding steps are short-lived cards, so no scroll observer.
 */
export function RoughMark({
    children,
    type,
    color,
    strokeWidth = 2,
    padding = 2,
    multiline = false,
    delay = 0,
}: {
    children: React.ReactNode
    type: 'underline' | 'highlight'
    color: string
    strokeWidth?: number
    padding?: number
    multiline?: boolean
    delay?: number
}): JSX.Element {
    const ref = useRef<HTMLSpanElement>(null)

    useEffect(() => {
        if (!ref.current) {
            return
        }
        const annotation: RoughAnnotation = annotate(ref.current, {
            type,
            color,
            strokeWidth,
            padding,
            multiline,
            iterations: 2,
            animationDuration: 800,
        })
        const timeout = window.setTimeout(() => annotation.show(), delay)
        return () => {
            window.clearTimeout(timeout)
            annotation.remove()
        }
    }, [type, color, strokeWidth, padding, multiline, delay])

    return <span ref={ref}>{children}</span>
}
