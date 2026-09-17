import { useEffect, useState } from 'react'

import { usePageVisibility } from 'lib/hooks/usePageVisibility'

interface ElapsedTimeProps {
    startTime: string | null | undefined
}

export function ElapsedTime({ startTime }: ElapsedTimeProps): JSX.Element | null {
    const [elapsedSeconds, setElapsedSeconds] = useState<number>(0)
    const { isVisible: isPageVisible } = usePageVisibility()

    useEffect(() => {
        if (!startTime || !isPageVisible) {
            return
        }

        const updateElapsed = (): void => {
            const start = new Date(startTime).getTime()
            const now = Date.now()
            const elapsed = Math.floor((now - start) / 1000)
            setElapsedSeconds(Math.max(0, elapsed))
        }

        updateElapsed()

        const interval = setInterval(updateElapsed, 1000)

        return () => clearInterval(interval)
    }, [startTime, isPageVisible])

    if (!startTime) {
        return null
    }

    const formatElapsedTime = (seconds: number): string => {
        const minutes = Math.floor(seconds / 60)
        const remainingSeconds = seconds % 60
        return `${minutes}:${remainingSeconds.toString().padStart(2, '0')}`
    }

    // Wrapped in an element rather than returned bare, because a bare text node lands among the
    // caller's children and React removes it directly once `startTime` goes away. If a
    // page-translation extension has swapped it for a <font> element by then, that removal throws
    // removeChild NotFoundError (react#11538). A clock has nothing to translate anyway.
    return <span translate="no">{formatElapsedTime(elapsedSeconds)}</span>
}
