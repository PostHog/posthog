import { useActions, useValues } from 'kea'
import { useEffect } from 'react'
import { insightLogic } from '../insightLogic'

const LIVE_MODE_INTERVAL_MS = 3000

/** Reload results periodically when the insight is in Live mode. Only works if insightLogic is bound. */
export function useLiveMode(): void {
    const { liveMode } = useValues(insightLogic)
    const { loadResults } = useActions(insightLogic)

    useEffect(() => {
        if (liveMode) {
            loadResults(true)
            const timeout = setInterval(() => {
                loadResults(true)
            }, LIVE_MODE_INTERVAL_MS)
            return () => clearInterval(timeout)
        }
    }, [liveMode])
}
