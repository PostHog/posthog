import { useEffect, useRef, useState } from 'react'

export function usePeriodicRerender(milliseconds: number): void {
    const [, setTick] = useState(0)
    const intervalIdRef = useRef<NodeJS.Timeout | null>(null)

    useEffect(() => {
        const isPageActive = (): boolean => !document.hidden && document.hasFocus()

        const startInterval = (triggerImmediately: boolean): void => {
            if (intervalIdRef.current) {
                return
            }
            if (triggerImmediately) {
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

        const handleVisibilityOrFocusChange = (): void => {
            if (isPageActive()) {
                startInterval(true)
            } else {
                stopInterval()
            }
        }

        if (isPageActive()) {
            startInterval(false)
        }

        document.addEventListener('visibilitychange', handleVisibilityOrFocusChange)
        window.addEventListener('focus', handleVisibilityOrFocusChange)
        window.addEventListener('blur', handleVisibilityOrFocusChange)

        return () => {
            stopInterval()
            document.removeEventListener('visibilitychange', handleVisibilityOrFocusChange)
            window.removeEventListener('focus', handleVisibilityOrFocusChange)
            window.removeEventListener('blur', handleVisibilityOrFocusChange)
        }
    }, [milliseconds, setTick])
}
