import posthog from 'posthog-js'

/**
 * Usage tracking for the sessions list. Clicks have no event here: autocapture records them,
 * and the elements carry `data-attr` values that name them.
 */

// pinned: event names and property keys. Dashboards, insights and usage analysis read them, so a rename breaks them.
const EVENTS = {
    listLoaded: 'llma sessions list loaded',
} as const

export interface SessionsListLoaded {
    rowsWaitMs: number
    rowCount: number
    dateFrom: string | null
    searched: boolean
}

export const sessionsTracking = {
    /**
     * Sent each time the first page answers: when the list opens, when its filters or date range change, and when it
     * reloads. `rows_wait_ms` is the wait for that read and `row_count` counts the sessions of the page.
     */
    listLoaded: ({ rowsWaitMs, rowCount, dateFrom, searched }: SessionsListLoaded): void => {
        posthog.capture(EVENTS.listLoaded, {
            rows_wait_ms: rowsWaitMs,
            row_count: rowCount,
            date_from: dateFrom,
            searched,
        })
    },
}
