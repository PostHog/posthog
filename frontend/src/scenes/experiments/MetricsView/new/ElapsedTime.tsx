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

    return <>{formatElapsedTime(elapsedSeconds)}</>
}
