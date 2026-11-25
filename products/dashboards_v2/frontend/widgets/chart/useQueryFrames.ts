import { useContext, useEffect, useRef, useState } from 'react'

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

/**
 * Carries each query's last result over to its new request. A query is matched by its key, so removing one target does
 * not hand its frames to the next. An edited query has a new key, and while the number of queries stays the same it
 * keeps the result at its position.
 */
export function carryOverResults(
    previousKeys: string[],
    previous: QueryFrames[],
    keys: string[],
    fresh: (key: string) => QueryFrames
): QueryFrames[] {
    return keys.map((key, index) => {
        const at = previousKeys.indexOf(key)
        const match = at >= 0 ? previous[at] : keys.length === previousKeys.length ? previous[index] : undefined
        return match ? afterRequestChange(match, fresh(key)) : fresh(key)
    })
}

/** Runs a chart's queries through the host's runner, and again when a query, its time range or the dashboard refresh changes. */
export function useQueryFrames(requests: QueryRequest[], runQuery: RunQuery): QueryFrames[] {
    // An edit rebuilds the request objects, so the queries run again only when their content changes.
    const queryKeys = requests.map((request) => JSON.stringify(request))
    const keysKey = JSON.stringify(queryKeys)
    const refresh = useContext(RefreshContext)
    const [results, setResults] = useState<QueryFrames[]>(() => queryKeys.map((key) => initial(runQuery, key, refresh)))
    const resultKeys = useRef(queryKeys)
    useEffect(() => {
        let cancelled = false
        const keys = JSON.parse(keysKey) as string[]
        const previousKeys = resultKeys.current
        resultKeys.current = keys
        const show = (index: number, next: QueryFrames): void =>
            setResults((previous) => {
                if (previous[index] && unchanged(previous[index], next)) {
                    return previous
                }
                const updated = [...previous]
                updated[index] = next
                return updated
            })
        setResults((previous) => {
            const next = carryOverResults(previousKeys, previous, keys, (key) => initial(runQuery, key, refresh))
            return next.length === previous.length && next.every((one, index) => one === previous[index])
                ? previous
                : next
        })
        keys.forEach((key, index) =>
            runCachedQuery(runQuery, key, refresh).then(
                (result) => !cancelled && show(index, { status: 'ready', refreshing: false, ...result }),
                (error: unknown) =>
                    !cancelled &&
                    show(index, { status: 'error', message: error instanceof Error ? error.message : String(error) })
            )
        )
        return () => {
            cancelled = true
        }
    }, [keysKey, runQuery, refresh])
    return results
}
