import { useEffect, useRef, useState } from 'react'

import { usePageVisibilityCb } from './usePageVisibility'

export function usePeriodicRerender(milliseconds: number): void {
    const [, setTick] = useState(0)
    const intervalIdRef = useRef<NodeJS.Timeout | null>(null)
    const isPageVisibleRef = useRef<boolean>(!document.hidden)

    const checkAndUpdateInterval = useRef<(() => void) | null>(null)

    usePageVisibilityCb((isVisible) => {
        isPageVisibleRef.current = isVisible
        checkAndUpdateInterval.current?.()
    })

    useEffect(() => {
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

        const handleVisibilityChange = (): void => {
            if (isPageVisibleRef.current) {
                startInterval(true)
            } else {
                stopInterval()
            }
        }

        checkAndUpdateInterval.current = handleVisibilityChange

        if (isPageVisibleRef.current) {
            startInterval(false)
        }

        return () => {
            stopInterval()
            checkAndUpdateInterval.current = null
        }
    }, [milliseconds])
}
