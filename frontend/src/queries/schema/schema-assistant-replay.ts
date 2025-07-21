import {
    EventPropertyFilter,
    FilterLogicalOperator,
    PersonPropertyFilter,
    RecordingDurationFilter,
    RecordingPropertyFilter,
    SessionPropertyFilter,
} from '~/types'

import { RecordingsQuery } from './schema-general'

// Subset of RecordingUniversalFilters that is more tractable for the AI assistant
export interface MaxRecordingUniversalFilters {
    /** The start date of the recording. If not provided, the default value is the last 5 days.
     * Relative Date (Days): Use the format '-Nd' for the last N days (e.g., 'last 5 days' becomes '-5d')
     * Relative Date (Hours): Use the format '-Nh' for the last N hours (e.g., 'last 5 hours' becomes '-5h')
     * Custom Date: If a specific start date is provided, use the format ISO8601 date string
     * @default '-5d'
     */
    date_from?: string | null
    /** ISO8601 date string. The end date of the recording. If not provided, the default value is today. */
    date_to?: string | null
    /** The duration of the recording. If not provided, the default value is an empty list.
     * @default []
     */
    duration: RecordingDurationFilter[]
    /** Whether to filter test accounts. */
    filter_test_accounts?: boolean
    /** The filter group of the recording. */
    filter_group: MaxOuterUniversalFiltersGroup
    /** The order of the recordings
     * @default 'start_time'
     */
    order?: RecordingsQuery['order']
}

export type MaxOuterUniversalFiltersGroup = {
    /** Defines how filters should be combined */
    type: FilterLogicalOperator
    /** The filter groups and their values to be applied to the recordings */
    values: MaxInnerUniversalFiltersGroup[]
}

export type MaxInnerUniversalFiltersGroup = {
    /** Defines how filters should be combined */
    type: FilterLogicalOperator
    /** The filters and their values to be applied to the recordings */
    values: MaxUniversalFilterValue[]
}

export type MaxUniversalFilterValue =
    | EventPropertyFilter
    | PersonPropertyFilter
    | SessionPropertyFilter
    | RecordingPropertyFilter
