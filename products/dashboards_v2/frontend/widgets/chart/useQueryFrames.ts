import { useEffect, useState } from 'react'

import { cachedFrames, runCachedQuery } from './queryCache'
import type { DataFrame, RunQuery, WidgetQuery } from './vizTypes'

export type QueryFrames =
    | { status: 'loading' }
    | { status: 'error'; message: string }
    | { status: 'ready'; frames: DataFrame[] }

function initial(runQuery: RunQuery, queryKey: string): QueryFrames {
    const frames = cachedFrames(runQuery, queryKey)
    return frames ? { status: 'ready', frames } : { status: 'loading' }
}

/** Runs a chart's query through the host's runner, and again whenever the query changes. */
export function useQueryFrames(query: WidgetQuery, runQuery: RunQuery): QueryFrames {
    // An edit rebuilds the query object, so the query runs again only when its content changes.
    const queryKey = JSON.stringify(query)
    const [result, setResult] = useState<QueryFrames>(() => initial(runQuery, queryKey))
    useEffect(() => {
        let cancelled = false
        setResult(initial(runQuery, queryKey))
        runCachedQuery(runQuery, queryKey).then(
            (frames) => !cancelled && setResult({ status: 'ready', frames }),
            (error: unknown) =>
                !cancelled &&
                setResult({ status: 'error', message: error instanceof Error ? error.message : String(error) })
        )
        return () => {
            cancelled = true
        }
    }, [queryKey, runQuery])
    return result
}
