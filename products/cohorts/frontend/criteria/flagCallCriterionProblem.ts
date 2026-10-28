import { isEventPropertyFilter } from 'lib/components/PropertyFilters/utils'

import {
    AnyCohortCriteriaType,
    AnyPropertyFilter,
    BehavioralEventType,
    EventPropertyFilter,
    PropertyOperator,
} from '~/types'

// The criterion types the cohorts API accepts on an event hidden in query builders. "Did not complete
// event" stores PerformEvent with negation.
export const CRITERIA_ACCEPTING_HIDDEN_EVENTS: string[] = [
    BehavioralEventType.PerformEvent,
    BehavioralEventType.PerformMultipleEvents,
]

export const MAX_LOOKBACK_DAYS = 88
const MAX_LOOKBACK_HOURS = MAX_LOOKBACK_DAYS * 24
const UNIT_MAX_HOURS: Record<string, number> = { h: 1, d: 24, w: 7 * 24, m: 31 * 24 }
const RELATIVE_DATE_PATTERN = /^-(\d+)([hdwm])$/
// Python's json.loads reads these, and JSON.parse does not.
const PYTHON_ONLY_JSON_CONSTANTS = new Set(['NaN', 'Infinity', '-Infinity'])

export type FlagCallCriterionProblem = 'type' | 'window' | 'flag-key'

/**
 * Why the batch calculation can't read this "Feature flag called" criterion from flag_evaluations, or null.
 *
 * Mirrors the checks in `posthog/api/cohort.py`, which explain the 88-day limit. The API checks the flag key
 * by compiling the query. This function checks the filters that a criterion row can hold, with the flag key rule
 * from `_is_flag_key` in `posthog/hogql/transforms/flag_calls_from_flag_evaluations.py`.
 */
export function flagCallCriterionProblem(criteria: AnyCohortCriteriaType): FlagCallCriterionProblem | null {
    if (!CRITERIA_ACCEPTING_HIDDEN_EVENTS.includes(String(criteria.value))) {
        return 'type'
    }
    if (!windowFitsRetention(criteria)) {
        return 'window'
    }
    if (!pinsFlagKeys(criteria.event_filters ?? [])) {
        return 'flag-key'
    }
    return null
}

function windowStart(criteria: AnyCohortCriteriaType): string | null {
    if (criteria.explicit_datetime) {
        return criteria.explicit_datetime
    }
    const count = Number(criteria.time_value)
    if (!Number.isInteger(count) || count <= 0 || !criteria.time_interval) {
        return null
    }
    return `-${count}${criteria.time_interval[0]}`
}

function windowFitsRetention(criteria: AnyCohortCriteriaType): boolean {
    const match = windowStart(criteria)?.match(RELATIVE_DATE_PATTERN)
    if (!match) {
        return false
    }
    const [, count, unit] = match
    return Number(count) * UNIT_MAX_HOURS[unit] <= MAX_LOOKBACK_HOURS
}

function parsesAsJson(key: string): boolean {
    if (PYTHON_ONLY_JSON_CONSTANTS.has(key.trim())) {
        return true
    }
    try {
        JSON.parse(key)
        return true
    } catch {
        return false
    }
}

function isFlagKeyFilter(filter: EventPropertyFilter): boolean {
    // A stored filter can omit the operator. The API reads a missing operator as exact.
    if (filter.key !== '$feature_flag' || (filter.operator ?? PropertyOperator.Exact) !== PropertyOperator.Exact) {
        return false
    }
    const keys = Array.isArray(filter.value) ? filter.value : [filter.value]
    return keys.length > 0 && keys.every((key) => typeof key === 'string' && key.length > 0 && !parsesAsJson(key))
}

// Only event property filters are known to resolve on flag_evaluations, so any other filter type counts as a problem.
function pinsFlagKeys(filters: AnyPropertyFilter[]): boolean {
    const eventFilters = filters.filter(isEventPropertyFilter)
    return eventFilters.length === filters.length && eventFilters.some(isFlagKeyFilter)
}
