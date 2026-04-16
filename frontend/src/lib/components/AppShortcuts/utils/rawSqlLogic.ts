import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api, { getCookie } from 'lib/api'

import type { rawSqlLogicType } from './rawSqlLogicType'

let activeAbortController: AbortController | null = null

function killQuery(queryId: string): void {
    // Use raw fetch so it doesn't depend on a free Django worker
    void fetch('/api/debug_ch_queries/cancel_query/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken') || getCookie('posthog_csrftoken') || '',
        },
        body: JSON.stringify({ query_id: queryId }),
        keepalive: true,
    })
}

export interface RawSqlColumn {
    name: string
    type: string
}

export interface RawSqlResult {
    columns: RawSqlColumn[]
    rows: any[][]
    query_id: string
    execution_time_ms: number
    truncated: boolean
}

export interface QueryLogEntry {
    status: 'complete' | 'pending'
    entry: Record<string, any>
}

const DEFAULT_QUERY = 'SELECT 1'

export const rawSqlLogic = kea<rawSqlLogicType>([
    path(['lib', 'components', 'CommandPalette', 'rawSqlLogic']),
    actions({
        setQuery: (query: string) => ({ query }),
        runQuery: true,
        cancelQuery: true,
        setRunningQueryId: (queryId: string | null) => ({ queryId }),
        loadQueryLog: (queryId: string) => ({ queryId }),
    }),
    reducers({
        query: [DEFAULT_QUERY, { setQuery: (_, { query }) => query }],
        runningQueryId: [
            null as string | null,
            {
                setRunningQueryId: (_, { queryId }) => queryId,
                runQuerySuccess: () => null,
                runQueryFailure: () => null,
            },
        ],
        rawSqlError: [
            null as string | null,
            {
                runQuery: () => null,
                runQueryFailure: (_, { errorObject, error }) => {
                    // errorObject is the full ApiError; error is just error.message
                    const detail = errorObject?.detail || errorObject?.data?.detail
                    if (detail) {
                        // DRF ValidationError wraps in an array
                        return Array.isArray(detail) ? detail.join(', ') : String(detail)
                    }
                    return String(error)
                },
            },
        ],
    }),
    loaders(({ values, actions }) => ({
        rawSqlResult: [
            null as RawSqlResult | null,
            {
                runQuery: async () => {
                    activeAbortController?.abort()
                    activeAbortController = new AbortController()
                    const queryId = `rawsql_${Math.random().toString(36).slice(2, 10)}`
                    actions.setRunningQueryId(queryId)
                    try {
                        return await api.create(
                            'api/debug_ch_queries/raw_sql/',
                            { query: values.query, query_id: queryId },
                            { signal: activeAbortController.signal }
                        )
                    } finally {
                        activeAbortController = null
                    }
                },
            },
        ],
        queryLogEntry: [
            null as QueryLogEntry | null,
            {
                loadQueryLog: async ({ queryId }: { queryId: string }) => {
                    const maxAttempts = 5
                    const intervalMs = 1000
                    for (let i = 0; i < maxAttempts; i++) {
                        if (i > 0) {
                            await new Promise((resolve) => setTimeout(resolve, intervalMs))
                        }
                        const result = await api.get(`api/debug_ch_queries/query_log_entry/?query_id=${queryId}`)
                        if (result.status === 'complete') {
                            return result as QueryLogEntry
                        }
                    }
                    return null
                },
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        runQuerySuccess: ({ rawSqlResult }) => {
            if (rawSqlResult?.query_id) {
                actions.loadQueryLog(rawSqlResult.query_id)
            }
        },
        cancelQuery: () => {
            activeAbortController?.abort()
            activeAbortController = null
            // Read before clearing — reducers run before listeners in kea
            const queryId = values.runningQueryId
            actions.setRunningQueryId(null)
            if (queryId) {
                killQuery(queryId)
            }
        },
    })),
    afterMount(({ actions }) => {
        // Load query from URL hash if present
        const hash = window.location.hash
        if (hash.startsWith('#q=')) {
            try {
                const query = decodeURIComponent(hash.slice(3))
                actions.setQuery(query)
            } catch {
                // ignore malformed hash
            }
        }
    }),
])
