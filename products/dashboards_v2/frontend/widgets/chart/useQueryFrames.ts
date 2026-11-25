import { useContext, useEffect, useState } from 'react'

import { RefreshContext } from '../refreshContext'
import { cachedResult, runCachedQuery } from './queryCache'
import type { QueryRequest, QueryResult, RunQuery } from './vizTypes'

export type QueryFrames =
    | { status: 'loading' }
    | { status: 'error'; message: string }
    | ({ status: 'ready'; refreshing: boolean } & QueryResult)

// A result from before the latest refresh shows as refreshing, so the chart is marked busy until the new one lands.
function initial(runQuery: RunQuery, queryKey: string, refresh: number): QueryFrames {
    const cached = cachedResult(runQuery, queryKey, refresh)
    return cached ? { status: 'ready', refreshing: cached.stale, ...cached.result } : { status: 'loading' }
}

// The cache hands back the same frames array, so a remounted tile keeps its state and its chart skips a rebuild.
function unchanged(previous: QueryFrames, next: QueryFrames): boolean {
    if (previous.status === 'ready' && next.status === 'ready') {
        return previous.frames === next.frames && previous.refreshing === next.refreshing
    }
    return previous.status === 'loading' && next.status === 'loading'
}

// Keeping the last result while a new request runs stops a time range change from blanking every tile.
export function afterRequestChange(previous: QueryFrames, cached: QueryFrames): QueryFrames {
    if (cached.status === 'loading' && previous.status === 'ready') {
        return previous.refreshing ? previous : { ...previous, refreshing: true }
    }
    return unchanged(previous, cached) ? previous : cached
}

/** Runs a chart's query through the host's runner, and again when the query, its time range or the dashboard refresh changes. */
export function useQueryFrames(request: QueryRequest, runQuery: RunQuery): QueryFrames {
    // An edit rebuilds the request object, so the query runs again only when its content changes.
    const queryKey = JSON.stringify(request)
    const refresh = useContext(RefreshContext)
    const [result, setResult] = useState<QueryFrames>(() => initial(runQuery, queryKey, refresh))
    useEffect(() => {
        let cancelled = false
        const show = (next: QueryFrames): void => setResult((previous) => (unchanged(previous, next) ? previous : next))
        setResult((previous) => afterRequestChange(previous, initial(runQuery, queryKey, refresh)))
        runCachedQuery(runQuery, queryKey, refresh).then(
            (result) => !cancelled && show({ status: 'ready', refreshing: false, ...result }),
            (error: unknown) =>
                !cancelled && show({ status: 'error', message: error instanceof Error ? error.message : String(error) })
        )
        return () => {
            cancelled = true
        }
    }, [queryKey, runQuery, refresh])
    return result
}
