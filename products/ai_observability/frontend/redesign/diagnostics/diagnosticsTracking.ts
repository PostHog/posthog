import posthog from 'posthog-js'

/**
 * Usage tracking for Diagnostics, the errors and tools lists and their drawers. Clicks have no event here: autocapture
 * records them, and the lists' elements carry `data-attr` values that name them.
 */

// pinned: event names and property keys and values. Dashboards, insights and usage analysis read them, so a rename
// breaks them.
const EVENTS = {
    entityOpened: 'llma diagnostics entity opened',
    readFailed: 'llma diagnostics read failed',
} as const

export type DiagnosticsEntityKind = 'error' | 'tool'

export interface DiagnosticsEntityOpened {
    kind: DiagnosticsEntityKind
    trigger: 'row' | 'url'
}

export interface DiagnosticsReadFailed {
    kind: DiagnosticsEntityKind
    read: 'list' | 'detail' | 'recent_traces' | 'first_seen' | 'new_count'
}

export const diagnosticsTracking = {
    /**
     * Sent each time an error or a tool opens in its drawer. `trigger` is `row` when the person opened it from the
     * list, and `url` when the page opened with it already in the URL, such as from a shared link.
     */
    entityOpened: ({ kind, trigger }: DiagnosticsEntityOpened): void => {
        posthog.capture(EVENTS.entityOpened, { kind, trigger })
    },
    /**
     * Sent each time a read fails: a page of the list, the drawer's detail or recent traces, the errors' first seen, or
     * the count of new errors. First seen is also read for the error open in the drawer when it is off the page, where
     * a failure only leaves out the New tag. A date range the server refuses as too long sends nothing for the list, the
     * drawer's detail and recent traces, and the count of new errors, because the list shows the range banner instead.
     */
    readFailed: ({ kind, read }: DiagnosticsReadFailed): void => {
        posthog.capture(EVENTS.readFailed, { kind, read })
    },
}
