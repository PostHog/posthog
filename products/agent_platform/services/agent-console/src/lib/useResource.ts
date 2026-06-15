/**
 * `useResource` — minimal data-fetching hook.
 *
 * Wraps a promise factory in `{ data, error, loading, reload }`. Used
 * everywhere the console reads from `apiClient`. Intentionally tiny —
 * react-query is overkill for v0; if we need cache invalidation,
 * suspense, retries, etc. we'll swap to it later.
 *
 * Implicitly subscribes to `useReloadKey()` so every read refetches
 * when the dock's focus handler navigates (even when the URL is
 * unchanged). Pass an explicit `deps` array for slug/id changes; the
 * reload key is folded in automatically.
 */

'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

import { startInFlight } from './loadingIndicator'
import { useReloadKey } from './reloadSignal'

export interface ResourceState<T> {
    data: T | null
    error: Error | null
    loading: boolean
    reload: () => void
    /**
     * Wall-clock ms at which the resource last settled (success or
     * error). `null` until the first settle. Used by
     * `<RefreshIndicator>` to render "updated 5s ago".
     */
    lastFetchedAt: number | null
}

export interface UseResourceOptions {
    /**
     * If set, refetch every `pollMs` milliseconds while the tab is
     * visible. Ticks are skipped while `document.hidden` (background
     * tab), and one catch-up reload fires on `visibilitychange` back to
     * visible — so a backgrounded view shows fresh data the moment it's
     * looked at again without hammering the API while hidden. Leave
     * unset for one-shot reads (the default).
     */
    pollMs?: number
}

export function useResource<T>(
    factory: () => Promise<T>,
    deps: unknown[] = [],
    options: UseResourceOptions = {}
): ResourceState<T> {
    const { pollMs } = options
    const reloadKey = useReloadKey()
    const [data, setData] = useState<T | null>(null)
    const [error, setError] = useState<Error | null>(null)
    const [loading, setLoading] = useState(true)
    const [lastFetchedAt, setLastFetchedAt] = useState<number | null>(null)
    const [manualReloadKey, setManualReloadKey] = useState(0)
    const reqIdRef = useRef(0)
    const factoryRef = useRef(factory)
    factoryRef.current = factory

    useEffect(() => {
        const myReqId = ++reqIdRef.current
        setLoading(true)
        const releaseInFlight = startInFlight()
        let released = false
        const release = (): void => {
            if (released) {
                return
            }
            released = true
            releaseInFlight()
        }
        factoryRef
            .current()
            .then((result) => {
                release()
                if (myReqId !== reqIdRef.current) {
                    return
                }
                setData(result)
                setError(null)
                setLoading(false)
                setLastFetchedAt(Date.now())
            })
            .catch((err) => {
                release()
                if (myReqId !== reqIdRef.current) {
                    return
                }
                setError(err instanceof Error ? err : new Error(String(err)))
                setLoading(false)
                setLastFetchedAt(Date.now())
            })
        // Stale-effect cleanup: a deps change before settle should still
        // decrement the counter so it doesn't stick high.
        return release
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [...deps, reloadKey, manualReloadKey])

    const reload = useCallback(() => setManualReloadKey((k) => k + 1), [])

    // Visibility-aware polling. The interval only fires `reload` when the
    // tab is foreground; switching back to a visible tab triggers one
    // immediate catch-up so stale background data refreshes on focus.
    useEffect(() => {
        if (!pollMs) {
            return
        }
        const tick = (): void => {
            if (!document.hidden) {
                reload()
            }
        }
        const onVisible = (): void => {
            if (!document.hidden) {
                reload()
            }
        }
        const id = setInterval(tick, pollMs)
        document.addEventListener('visibilitychange', onVisible)
        return () => {
            clearInterval(id)
            document.removeEventListener('visibilitychange', onVisible)
        }
    }, [pollMs, reload])

    return { data, error, loading, reload, lastFetchedAt }
}
