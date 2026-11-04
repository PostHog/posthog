import { isEventPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { AnyCohortCriteriaType, BehavioralEventType } from '~/types'

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

export type FlagCallCriterionProblem = 'type' | 'window' | 'filters'

/**
 * Why the batch calculation can't count every matching call for this "Feature flag called" criterion once flag calls
 * are only in flag_evaluations, or null.
 *
 * Mirrors the type, window and filter checks in `posthog/api/cohort.py`, which explain the 88-day limit and why the
 * API refuses a SQL expression filter on this event. The filter check also flags element filters, which the API
 * accepts.
 */
export function flagCallCriterionProblem(criteria: AnyCohortCriteriaType): FlagCallCriterionProblem | null {
    if (!CRITERIA_ACCEPTING_HIDDEN_EVENTS.includes(String(criteria.value))) {
        return 'type'
    }
    if (!windowFitsRetention(criteria)) {
        return 'window'
    }
    if (!(criteria.event_filters ?? []).every(isEventPropertyFilter)) {
        return 'filters'
    }
    return null
}

/** The problem to warn about when the criterion names one of the events that are moving, or null. */
export function moveNoticeProblem(
    criteria: AnyCohortCriteriaType,
    moveNoticeEvents: string[]
): FlagCallCriterionProblem | null {
    const namesMovingEvent =
        (criteria.event_type === TaxonomicFilterGroupType.Events && moveNoticeEvents.includes(String(criteria.key))) ||
        (criteria.seq_event_type === TaxonomicFilterGroupType.Events &&
            moveNoticeEvents.includes(String(criteria.seq_event)))
    return namesMovingEvent ? flagCallCriterionProblem(criteria) : null
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
