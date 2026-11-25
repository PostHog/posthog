import posthog from 'posthog-js'

import type { AiObservabilityPeopleListOrder } from '../../generated/api.schemas'

/**
 * Usage tracking for the people list and its person drawer. Clicks have no event here: autocapture records them, and the elements carry
 * `data-attr` values that name them.
 */

// pinned: event names and property keys. Dashboards, insights and usage analysis read them, so a rename breaks them.
const EVENTS = {
    listLoaded: 'llma people list loaded',
    listFailed: 'llma people list failed',
    drawerSectionFailed: 'llma person drawer section failed',
} as const

export type PersonDrawerSection = 'person' | 'recent_traces' | 'recent_sessions'

export interface PeopleListRead {
    order: AiObservabilityPeopleListOrder
    includeAnonymous: boolean
}

export interface PeopleListLoaded extends PeopleListRead {
    count: number
    loadMs: number
}

export const peopleTracking = {
    /**
     * Sent each time a page answers: when the list opens, when its filters, order or date range change, when it steps
     * to another page, and when it reloads. `count` counts the people of every page and `load_ms` is the wait for
     * this one.
     */
    listLoaded: ({ count, order, includeAnonymous, loadMs }: PeopleListLoaded): void => {
        posthog.capture(EVENTS.listLoaded, { count, order, include_anonymous: includeAnonymous, load_ms: loadMs })
    },
    /** Sent each time a page fails to load, with the order and anonymous switch it was read with. */
    listFailed: ({ order, includeAnonymous }: PeopleListRead): void => {
        posthog.capture(EVENTS.listFailed, { order, include_anonymous: includeAnonymous })
    },
    /** Sent each time a read of the person drawer fails: the person, their recent traces or their recent sessions. */
    drawerSectionFailed: (section: PersonDrawerSection): void => {
        posthog.capture(EVENTS.drawerSectionFailed, { section })
    },
}
