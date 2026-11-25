import { useEffect, useState } from 'react'

import { cachedResult, runCachedQuery } from './queryCache'
import type { QueryRequest, QueryResult, RunQuery } from './vizTypes'

export type QueryFrames =
    | { status: 'loading' }
    | { status: 'error'; message: string }
    | ({ status: 'ready'; refreshing: boolean } & QueryResult)

function initial(runQuery: RunQuery, queryKey: string): QueryFrames {
    const result = cachedResult(runQuery, queryKey)
    return result ? { status: 'ready', refreshing: false, ...result } : { status: 'loading' }
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

/** Runs a chart's queries through the host's runner, and again whenever a query or its time range changes. */
export function useQueryFrames(requests: QueryRequest[], runQuery: RunQuery): QueryFrames[] {
    // An edit rebuilds the request objects, so the queries run again only when their content changes.
    const queryKeys = requests.map((request) => JSON.stringify(request))
    const keysKey = JSON.stringify(queryKeys)
    const [results, setResults] = useState<QueryFrames[]>(() => queryKeys.map((key) => initial(runQuery, key)))
    useEffect(() => {
        let cancelled = false
        const keys = JSON.parse(keysKey) as string[]
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
            const next = keys.map((key, index) =>
                previous[index] ? afterRequestChange(previous[index], initial(runQuery, key)) : initial(runQuery, key)
            )
            return next.length === previous.length && next.every((one, index) => one === previous[index])
                ? previous
                : next
        })
        keys.forEach((key, index) =>
            runCachedQuery(runQuery, key).then(
                (result) => !cancelled && show(index, { status: 'ready', refreshing: false, ...result }),
                (error: unknown) =>
                    !cancelled &&
                    show(index, { status: 'error', message: error instanceof Error ? error.message : String(error) })
            )
        )
        return () => {
            cancelled = true
        }
    }, [keysKey, runQuery])
    return results
}
