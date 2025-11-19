import { useEffect, useRef, useState } from 'react'

export function usePeriodicRerender(milliseconds: number): void {
    const [, setTick] = useState(0)
    const intervalIdRef = useRef<NodeJS.Timeout | null>(null)
    const isInitialMount = useRef(true)

    useEffect(() => {
        const isPageActive = (): boolean => {
            return !document.hidden && document.hasFocus()
        }

        const startInterval = (triggerImmediately: boolean = false): void => {
            if (intervalIdRef.current !== null) {
                return
            }
            // Trigger an immediate rerender if requested (when resuming from paused state)
            if (triggerImmediately) {
                setTick((state) => state + 1)
            }
            intervalIdRef.current = setInterval(() => setTick((state) => state + 1), milliseconds)
        }

        const stopInterval = (): void => {
            if (intervalIdRef.current !== null) {
                clearInterval(intervalIdRef.current)
                intervalIdRef.current = null
            }
        }

        const handleVisibilityOrFocusChange = (): void => {
            if (isPageActive()) {
                // When resuming from paused state, trigger immediate rerender
                startInterval(true)
            } else {
                stopInterval()
            }
        }

        // Start interval if page is currently active (no immediate trigger on mount)
        if (isPageActive()) {
            startInterval(false)
        }
        isInitialMount.current = false

        // Listen to visibility changes
        document.addEventListener('visibilitychange', handleVisibilityOrFocusChange)
        // Listen to focus/blur events
        window.addEventListener('focus', handleVisibilityOrFocusChange)
        window.addEventListener('blur', handleVisibilityOrFocusChange)

        return () => {
            stopInterval()
            document.removeEventListener('visibilitychange', handleVisibilityOrFocusChange)
            window.removeEventListener('focus', handleVisibilityOrFocusChange)
            window.removeEventListener('blur', handleVisibilityOrFocusChange)
        }
    }, [milliseconds])
}
