import { useEffect, useRef, useState } from 'react'

import { prefersReducedMotion } from '../motion'
import { monotonicNow } from '../time'

/** When `target` changes mid-animation, animation restarts from the currently-displayed value (no snap). */
export function useAnimatedNumber(target: number, duration = 120): number {
    const [value, setValue] = useState(target)
    // Written during render so the animation reads the latest value from the same render pass.
    const valueRef = useRef(value)
    valueRef.current = value

    useEffect(() => {
        if (duration <= 0 || !Number.isFinite(target) || prefersReducedMotion()) {
            setValue(target)
            return
        }
        const from = valueRef.current
        if (from === target) {
            return
        }
        const start = monotonicNow()
        let raf = 0
        // Measure elapsed with monotonicNow() rather than the rAF timestamp, so both sides of the
        // subtraction share one clock — otherwise the Date.now() fallback (when performance is
        // absent) mixes scales with the page-relative rAF timestamp and the eased value blows up.
        const tick = (): void => {
            const t = Math.min(1, (monotonicNow() - start) / duration)
            const eased = 1 - Math.pow(1 - t, 3)
            // The last frame sets the target itself, because `from + (target - from) * 1` can miss it by
            // one ulp and leave a caller that compares against the target waiting for good.
            setValue(t >= 1 ? target : from + (target - from) * eased)
            if (t < 1) {
                raf = requestAnimationFrame(tick)
            }
        }
        raf = requestAnimationFrame(tick)
        return () => cancelAnimationFrame(raf)
    }, [target, duration, valueRef])

    return value
}
