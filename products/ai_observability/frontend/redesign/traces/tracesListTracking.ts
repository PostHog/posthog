import posthog from 'posthog-js'

/**
 * Usage tracking for the traces list. Clicks have no event here: autocapture records them, and the list's elements
 * carry `data-attr` values that name them.
 */

// pinned: event names and property keys. Dashboards, insights and usage analysis read them, so a rename breaks them.
const EVENTS = {
    listLoaded: 'llma traces list loaded',
} as const

export interface TracesListLoaded {
    rowsWaitMs: number
    rowCount: number
    dateFrom: string | null
    quickFilter: string | null
    searched: boolean
}

export const tracesListTracking = {
    /**
     * Sent each time the first page answers: when the list opens, when its filters or date range change, and when it
     * reloads. `rows_wait_ms` is the wait for that read and `row_count` counts the rows of the page. `quick_filter`
     * is the quick filter the read applied, or null.
     */
    listLoaded: ({ rowsWaitMs, rowCount, dateFrom, quickFilter, searched }: TracesListLoaded): void => {
        posthog.capture(EVENTS.listLoaded, {
            rows_wait_ms: rowsWaitMs,
            row_count: rowCount,
            date_from: dateFrom,
            quick_filter: quickFilter,
            searched,
        })
    },
}
