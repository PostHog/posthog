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
    date_from?: string | null
    date_to?: string | null
    duration: RecordingDurationFilter[]
    filter_test_accounts?: boolean
    filter_group: MaxOuterUniversalFiltersGroup
    order?: RecordingsQuery['order']
    order_direction?: RecordingsQuery['order_direction']
}

export type MaxOuterUniversalFiltersGroup = {
    type: FilterLogicalOperator
    values: MaxInnerUniversalFiltersGroup[]
}

export type MaxInnerUniversalFiltersGroup = {
    type: FilterLogicalOperator
    values: MaxUniversalFilterValue[]
}

export type MaxUniversalFilterValue =
    | EventPropertyFilter
    | PersonPropertyFilter
    | SessionPropertyFilter
    | RecordingPropertyFilter
