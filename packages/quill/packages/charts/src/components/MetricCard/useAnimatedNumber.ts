import { useEffect, useRef, useState } from 'react'

import { monotonicNow } from '../../core/time'

/** When `target` changes mid-animation, animation restarts from the currently-displayed value (no snap). */
export function useAnimatedNumber(target: number, duration = 350): number {
    const [value, setValue] = useState(target)
    // Written during render so the animation reads the latest value from the same render pass.
    const valueRef = useRef(value)
    valueRef.current = value

    useEffect(() => {
        if (duration <= 0 || !Number.isFinite(target)) {
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
            setValue(from + (target - from) * eased)
            if (t < 1) {
                raf = requestAnimationFrame(tick)
            }
        }
        raf = requestAnimationFrame(tick)
        return () => cancelAnimationFrame(raf)
    }, [target, duration, valueRef])

    return value
}
