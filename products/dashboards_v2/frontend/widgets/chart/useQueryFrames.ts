import { useEffect, useState } from 'react'

import { cachedResult, runCachedQuery } from './queryCache'
import type { QueryRequest, QueryResult, RunQuery } from './vizTypes'

export type QueryFrames =
    | { status: 'loading' }
    | { status: 'error'; message: string }
    | ({ status: 'ready' } & QueryResult)

function initial(runQuery: RunQuery, queryKey: string): QueryFrames {
    const result = cachedResult(runQuery, queryKey)
    return result ? { status: 'ready', ...result } : { status: 'loading' }
}

// The cache hands back the same frames array, so a remounted tile keeps its state and its chart skips a rebuild.
function unchanged(previous: QueryFrames, next: QueryFrames): boolean {
    if (previous.status === 'ready' && next.status === 'ready') {
        return previous.frames === next.frames
    }
    return previous.status === 'loading' && next.status === 'loading'
}

/** Runs a chart's query through the host's runner, and again whenever the query or its time range changes. */
export function useQueryFrames(request: QueryRequest, runQuery: RunQuery): QueryFrames {
    // An edit rebuilds the request object, so the query runs again only when its content changes.
    const queryKey = JSON.stringify(request)
    const [result, setResult] = useState<QueryFrames>(() => initial(runQuery, queryKey))
    useEffect(() => {
        let cancelled = false
        const show = (next: QueryFrames): void => setResult((previous) => (unchanged(previous, next) ? previous : next))
        show(initial(runQuery, queryKey))
        runCachedQuery(runQuery, queryKey).then(
            (result) => !cancelled && show({ status: 'ready', ...result }),
            (error: unknown) =>
                !cancelled && show({ status: 'error', message: error instanceof Error ? error.message : String(error) })
        )
        return () => {
            cancelled = true
        }
    }, [queryKey, runQuery])
    return result
}
