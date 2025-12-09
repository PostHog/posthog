import clsx from 'clsx'
import { useEffect, useRef, useState } from 'react'

import { Logomark } from 'lib/brand/Logomark'

export interface AnimatedLogomarkProps {
    /** Animate the logomark continuously (e.g. during loading states) */
    animate: boolean
    /** Play a single animation cycle and call onAnimationComplete when done */
    animateOnce?: boolean
    /** Callback when a single animation cycle completes (only used with animateOnce) */
    onAnimationComplete?: () => void
    className?: string
}

/**
 * Animated PostHog logomark that jumps continuously while `animate` is true.
 *
 * When `animate` becomes false, the animation completes its current cycle before
 * stopping - it won't cut off mid-jump.
 *
 * When `animateOnce` is true, plays a single animation cycle and calls
 * `onAnimationComplete` when done.
 */
export function AnimatedLogomark({
    animate,
    animateOnce,
    onAnimationComplete,
    className,
}: AnimatedLogomarkProps): JSX.Element {
    const ref = useRef<HTMLDivElement | null>(null)
    const [isAnimating, setIsAnimating] = useState(false)
    const shouldStopRef = useRef(false)
    const onAnimationCompleteRef = useRef(onAnimationComplete)

    onAnimationCompleteRef.current = onAnimationComplete

    // Track stop intent via ref so the listener always sees current value
    // without needing to be re-attached when `animate` changes
    shouldStopRef.current = !animate && isAnimating

    // Start animation immediately when requested
    useEffect(() => {
        if (animate || animateOnce) {
            setIsAnimating(true)
        }
    }, [animate, animateOnce])

    // Set up iteration listener once when animation starts.
    // The listener checks shouldStopRef on each cycle to decide whether to stop.
    useEffect(() => {
        if (!isAnimating || !ref.current) {
            return
        }

        const animatedElement = ref.current.querySelector('svg > *')
        if (!animatedElement) {
            return
        }

        const handleAnimationIteration = (): void => {
            if (animateOnce) {
                setIsAnimating(false)
                onAnimationCompleteRef.current?.()
            } else if (shouldStopRef.current) {
                setIsAnimating(false)
            }
        }

        animatedElement.addEventListener('animationiteration', handleAnimationIteration)
        return () => {
            animatedElement.removeEventListener('animationiteration', handleAnimationIteration)
        }
    }, [isAnimating, animateOnce])

    return (
        <div ref={ref} className={clsx(className, isAnimating && 'animate-logomark-jump-continuous')}>
            <Logomark />
        </div>
    )
}
