import {
    EventPropertyFilter,
    FilterLogicalOperator,
    GroupPropertyFilter,
    PersonPropertyFilter,
    RecordingDurationFilter,
    RecordingPropertyFilter,
    SessionPropertyFilter,
} from '~/types'

import { AssistantPropertyFilter } from './schema-assistant-queries'
import { RecordingsQuery } from './schema-general'

// Subset of RecordingUniversalFilters that is more tractable for the AI assistant
export interface MaxRecordingUniversalFilters {
    date_from?: string | null
    date_to?: string | null
    duration: RecordingDurationFilter[]
    filter_test_accounts?: boolean
    filter_group: MaxOuterUniversalFiltersGroup
    order?: RecordingsQuery['order']
    order_direction?: RecordingsQuery['order_direction']
    /** How many recordings the user requested to use. Skip if user did not indicate preference. */
    limit?: RecordingsQuery['limit']
}

export type MaxOuterUniversalFiltersGroup = {
    type: FilterLogicalOperator
    values: MaxInnerUniversalFiltersGroup[]
}

export type MaxInnerUniversalFiltersGroup = {
    type: FilterLogicalOperator
    /**
     * Filter conditions for session recordings. Possible filter types:
     * - 'event' type: Filter by properties of events in the session (e.g. `$current_url` equals X).
     * - 'person' type: Filter by person properties (e.g. `email` contains Y).
     * - 'session' type: Filter by session-level properties (e.g. `$session_duration`).
     * - 'recording' type: Filter by recording metadata (e.g. `console_log_level`, `visited_page`).
     * - 'group' type: Filter by group properties (e.g. company `plan` is "enterprise").
     * - 'events' type: Filter by whether a specific event occurred (e.g. `$pageview` was present).
     */
    values: MaxUniversalFilterValue[]
}

// ActionFilter narrowed down to just an event with optional property filtering (because ActionFilter is a _mess_)
export interface MaxRecordingEventFilter {
    type: 'events'
    /** Name of the event. */
    id: string
    /** Optional display name for this event. */
    name?: string
    /** Optional property filters for this event only. */
    properties?: AssistantPropertyFilter[]
}

export type MaxUniversalFilterValue =
    | EventPropertyFilter
    | PersonPropertyFilter
    | SessionPropertyFilter
    | RecordingPropertyFilter
    | GroupPropertyFilter
    | MaxRecordingEventFilter
