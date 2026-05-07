import { useEffect, useRef, useState } from 'react'

import { usePageVisibility } from './usePageVisibility'

export function usePeriodicRerender(milliseconds: number): void {
    const [, setTick] = useState(0)
    const intervalIdRef = useRef<NodeJS.Timeout | null>(null)
    const { isVisible } = usePageVisibility()
    const wasVisibleRef = useRef(isVisible)

    useEffect(() => {
        const startInterval = (): void => {
            if (intervalIdRef.current) {
                return
            }
            // Trigger immediate rerender only when visibility changes from hidden to visible
            if (!wasVisibleRef.current && isVisible) {
                setTick((state) => state + 1)
            }
            intervalIdRef.current = setInterval(() => setTick((state) => state + 1), milliseconds)
        }

        const stopInterval = (): void => {
            if (intervalIdRef.current) {
                clearInterval(intervalIdRef.current)
                intervalIdRef.current = null
            }
        }

        // Pass 0 (or negative) to opt out of the interval entirely — useful for callers that only need to tick under specific conditions.
        if (isVisible && milliseconds > 0) {
            startInterval()
        } else {
            stopInterval()
        }

        wasVisibleRef.current = isVisible

        return stopInterval
    }, [milliseconds, isVisible])
}
