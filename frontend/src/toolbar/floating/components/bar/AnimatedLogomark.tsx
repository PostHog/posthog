import { useCallback, useEffect, useRef } from 'react'

import { Logo as BrandLogo } from '@posthog/brand/logo'
import type { LogomarkHandle } from '@posthog/brand/logo'

export interface AnimatedLogomarkProps {
    /** Jump continuously (e.g. during toolbar loading states). */
    animate: boolean
    /** Play a single jump, then invoke this callback. */
    animateOnce?: () => void
    className?: string
}

// The package hop lasts ~airtimeMs (default 400); pace continuous jumps a touch slower so each hop
// lands with a beat of rest before the next.
const JUMP_AIRTIME_MS = 400
const JUMP_CADENCE_MS = 900

/**
 * Toolbar logomark that jumps while `animate` is true (finishing its in-flight hop before stopping)
 * or exactly once when `animateOnce` is set. Jumps are driven through the package's imperative
 * `ref.current.jump()` on the single mono mark (the render below explains why mono). `animateOnce`
 * ALWAYS calls back, even when the jump is suppressed (no WAAPI / reduced-motion → `jump()` returns
 * `false`), because the toolbar's graceful exit chains logout off it.
 */
export function AnimatedLogomark({ animate, animateOnce, className }: AnimatedLogomarkProps): JSX.Element {
    const markRef = useRef<LogomarkHandle>(null)

    const animateOnceRef = useRef(animateOnce)
    animateOnceRef.current = animateOnce

    // Returns whether the hop actually started (false = suppressed: in-flight / no WAAPI / reduced-motion).
    const jump = useCallback((): boolean => markRef.current?.jump() ?? false, [])

    // Trigger on presence, not identity, so a re-created callback doesn't restart (and drop) the jump.
    const shouldAnimateOnce = animateOnce != null

    useEffect(() => {
        if (!shouldAnimateOnce) {
            return
        }
        let cancelled = false

        const finish = (): void => {
            if (!cancelled) {
                animateOnceRef.current?.()
            }
        }

        // Play the hop, then call back once it has landed; if the jump was suppressed, don't make
        // the caller (logout) wait for an animation that isn't happening.
        if (!jump()) {
            finish()
            return
        }

        const timer = setTimeout(finish, JUMP_AIRTIME_MS)
        return () => {
            cancelled = true
            clearTimeout(timer)
        }
    }, [shouldAnimateOnce, jump])

    useEffect(() => {
        if (!animate || shouldAnimateOnce) {
            return
        }

        // hop immediately, then keep pace; the in-flight hop finishes on its own when we stop
        jump()

        const interval = setInterval(jump, JUMP_CADENCE_MS)
        return () => clearInterval(interval)
    }, [animate, shouldAnimateOnce, jump])

    // `mono` renders a single `currentColor` fill, so the toolbar's own per-theme text color drives
    // the mark. It also avoids the gradient variant's `fill="url(#…)"` references, which don't resolve
    // inside the toolbar's shadow DOM on host pages (they'd leave only the head visible).
    // `overflow: visible` lets the hop escape the svg box (the package adds it only for its own jump
    // props, not for imperative jumps); the wrapping div carries `.Toolbar__logomark` for sizing.
    return (
        <div className={className}>
            <BrandLogo.Logomark ref={markRef} variant="mono" style={{ overflow: 'visible' }} />
        </div>
    )
}
