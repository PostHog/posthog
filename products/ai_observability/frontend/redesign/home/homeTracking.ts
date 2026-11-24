import posthog from 'posthog-js'

/**
 * Usage tracking for Home. Clicks have no event here: autocapture records them, and the tiles and the dashboard link
 * carry `data-attr` values that name them.
 */

// pinned: event name and property keys. Dashboards, insights and usage analysis read them, so a rename breaks them.
const EVENTS = {
    metricsLoaded: 'llma home metrics loaded',
} as const

export interface HomeMetricsLoaded {
    loadMs: number
    dateFrom: string
    dateTo: string | null
    filterTestAccounts: boolean
}

export const homeTracking = {
    /**
     * Sent each time the tiles answer: when Home opens, and when its date range or the test accounts switch changes.
     * `load_ms` is the wait for that read. `date_from` and `date_to` are the range the read used, and `date_to` is
     * null for a range that runs to now.
     */
    metricsLoaded: ({ loadMs, dateFrom, dateTo, filterTestAccounts }: HomeMetricsLoaded): void => {
        posthog.capture(EVENTS.metricsLoaded, {
            load_ms: loadMs,
            date_from: dateFrom,
            date_to: dateTo,
            filter_test_accounts: filterTestAccounts,
        })
    },
}
