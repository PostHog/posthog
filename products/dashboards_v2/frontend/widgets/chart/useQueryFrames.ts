import { useEffect, useState } from 'react'

import type { DataFrame, RunQuery, WidgetQuery } from './vizTypes'

export type QueryFrames =
    | { status: 'loading' }
    | { status: 'error'; message: string }
    | { status: 'ready'; frames: DataFrame[] }

/** Runs a chart's query through the host's runner, and again whenever the query changes. */
export function useQueryFrames(query: WidgetQuery, runQuery: RunQuery): QueryFrames {
    const [result, setResult] = useState<QueryFrames>({ status: 'loading' })
    // An edit rebuilds the query object, so the query runs again only when its content changes.
    const queryKey = JSON.stringify(query)
    useEffect(() => {
        let cancelled = false
        setResult({ status: 'loading' })
        runQuery(JSON.parse(queryKey) as WidgetQuery).then(
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
