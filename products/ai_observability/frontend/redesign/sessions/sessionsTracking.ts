import posthog from 'posthog-js'

/**
 * Usage tracking for the sessions list and the open conversation. Clicks have no event here: autocapture records them,
 * and the elements carry `data-attr` values that name them.
 */

// pinned: event names and property keys. Dashboards, insights and usage analysis read them, so a rename breaks them.
const EVENTS = {
    listLoaded: 'llma sessions list loaded',
    conversationLoaded: 'llma session conversation loaded',
} as const

export interface SessionsListLoaded {
    rowsWaitMs: number
    rowCount: number
    dateFrom: string | null
    searched: boolean
}

export interface SessionConversationLoaded {
    turnsWaitMs: number
    turnCount: number
    openedAround: boolean
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
    /**
     * Sent once per opened conversation, when its first page of turns answers, before their messages load. A first
     * page with no turns, or that fails to load, sends nothing. `turns_wait_ms` is the wait for that page and
     * `turn_count` counts its turns. `opened_around` is true when the conversation opened on a given turn, such as one
     * whose trace is open in the drawer, rather than on the first.
     */
    conversationLoaded: ({ turnsWaitMs, turnCount, openedAround }: SessionConversationLoaded): void => {
        posthog.capture(EVENTS.conversationLoaded, {
            turns_wait_ms: turnsWaitMs,
            turn_count: turnCount,
            opened_around: openedAround,
        })
    },
}
