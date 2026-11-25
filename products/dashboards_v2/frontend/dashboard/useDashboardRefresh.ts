import { useCallback, useEffect, useMemo, useState } from 'react'

import type { AutoRefreshProps } from './AutoRefreshButton'
import type { RefreshController } from './dashboardV2Context'

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
        const timer = window.setInterval(refreshNow, interval * 1000)
        return () => window.clearInterval(timer)
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
