import { useCallback, useEffect, useMemo, useState } from 'react'

import type { RefreshController } from '../core/dashboardContext'
import type { AutoRefreshProps } from './AutoRefreshButton'

/**
 * Calls `refresh` on every interval. Nobody sees a hidden page, so its refreshes wait and run as one when the person
 * comes back. Returns the stop function.
 */
export function startAutoRefresh(intervalMs: number, refresh: () => void): () => void {
    let missed = false
    const onTick = (): void => {
        if (document.hidden) {
            missed = true
        } else {
            refresh()
        }
    }
    const onVisibilityChange = (): void => {
        if (!document.hidden && missed) {
            missed = false
            refresh()
        }
    }
    const timer = window.setInterval(onTick, intervalMs)
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => {
        window.clearInterval(timer)
        document.removeEventListener('visibilitychange', onVisibilityChange)
    }
}

/** `count` goes up on every refresh, from the button or the timer, so each chart runs its query again. */
export function useDashboardRefresh(refresh: RefreshController | undefined): {
    count: number
    button: AutoRefreshProps | undefined
} {
    const [count, setCount] = useState(0)
    const [interval, setInterval] = useState(refresh?.initialInterval ?? null)
    const enabled = !!refresh
    const { intervals, refreshing, onRefresh: hostRefresh } = refresh ?? {}
    const refreshNow = useCallback((): void => {
        setCount((previous) => previous + 1)
        hostRefresh?.()
    }, [hostRefresh])

    useEffect(() => {
        if (!enabled || !interval) {
            return
        }
        return startAutoRefresh(interval * 1000, refreshNow)
    }, [enabled, interval, refreshNow])

    const button = useMemo(
        () =>
            enabled
                ? { intervals, refreshing, interval, onIntervalChange: setInterval, onRefresh: refreshNow }
                : undefined,
        [enabled, intervals, refreshing, interval, refreshNow]
    )
    return { count, button }
}
