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
        const isPageActive = (): boolean => isPageVisibleRef.current && document.hasFocus()

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

        const handleActiveStateChange = (): void => {
            if (isPageActive()) {
                startInterval(true)
            } else {
                stopInterval()
            }
        }

        checkAndUpdateInterval.current = handleActiveStateChange

        if (isPageActive()) {
            startInterval(false)
        }

        window.addEventListener('focus', handleActiveStateChange)
        window.addEventListener('blur', handleActiveStateChange)

        return () => {
            stopInterval()
            window.removeEventListener('focus', handleActiveStateChange)
            window.removeEventListener('blur', handleActiveStateChange)
            checkAndUpdateInterval.current = null
        }
    }, [milliseconds])
}
