import { isEventPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { isCohortCriteriaGroup } from 'scenes/cohorts/cohortUtils'
import { FEATURE_FLAG_CALLED_EVENT } from 'scenes/feature-flags/flagEvaluationsTable'

import { AnyCohortCriteriaType, BehavioralEventType, CohortCriteriaGroupFilter, CohortType } from '~/types'

// The criterion types the cohorts API accepts on an event hidden in query builders. "Did not complete
// event" stores PerformEvent with negation.
export const CRITERIA_ACCEPTING_HIDDEN_EVENTS: string[] = [
    BehavioralEventType.PerformEvent,
    BehavioralEventType.PerformMultipleEvents,
]

export const MAX_LOOKBACK_DAYS = 90
const MAX_LOOKBACK_HOURS = MAX_LOOKBACK_DAYS * 24
const UNIT_MAX_HOURS: Record<string, number> = { h: 1, d: 24, w: 7 * 24, m: 31 * 24 }
const RELATIVE_DATE_PATTERN = /^-(\d+)([hdwm])$/

export type FlagCallCriterionProblem = 'type' | 'window' | 'filters'

/** What happens to a criterion with each problem once PostHog stops writing flag calls to the events table. */
const FLAG_CALL_PROBLEM_EFFECTS: Record<FlagCallCriterionProblem, string> = {
    type: 'this criterion stops matching new flag calls. To keep it matching, change it to "Completed event", "Did not complete event" or "Completed an event multiple times".',
    window: `this criterion misses some flag calls. To count them all, use a range relative to today that goes back ${MAX_LOOKBACK_DAYS} days or less, such as "Last 30 days".`,
    filters:
        'PostHog may not be able to calculate this cohort. To keep it working, filter this criterion on event properties only.',
}

/**
 * Why the batch calculation can't count every matching call for this "Feature flag called" criterion once flag calls
 * are only in flag_evaluations, or null.
 *
 * Mirrors the type, window and filter checks in `posthog/api/cohort.py`, which explain the 90-day limit and why the
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

/** The step of the move that the problem follows from, in the words of the troubleshooting doc. */
function flagCallMoveLeadIn(writesStopped: boolean): string {
    return writesStopped
        ? 'PostHog no longer writes flag calls to the events table, so'
        : 'Once PostHog stops writing flag calls to the events table,'
}

/** What happens to a criterion with this problem, and how to fix it. `writesStopped` picks the step of the move. */
export function flagCallProblemText(problem: FlagCallCriterionProblem, writesStopped: boolean): string {
    return `${flagCallMoveLeadIn(writesStopped)} ${FLAG_CALL_PROBLEM_EFFECTS[problem]}`
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

function firstGroupProblem(group: CohortCriteriaGroupFilter): FlagCallCriterionProblem | null {
    const values: (AnyCohortCriteriaType | CohortCriteriaGroupFilter)[] = group.values
    for (const value of values) {
        const problem = isCohortCriteriaGroup(value)
            ? firstGroupProblem(value)
            : moveNoticeProblem(value, [FEATURE_FLAG_CALLED_EVENT])
        if (problem !== null) {
            return problem
        }
    }
    return null
}

/**
 * A static cohort keeps the people it already has. An experiment's exposure cohort is left out, because its
 * criterion belongs to the experiment.
 */
export function cohortSkipsFlagCallCheck(cohort: Pick<CohortType, 'is_static' | 'experiment_set'>): boolean {
    return !!cohort.is_static || !!cohort.experiment_set?.length
}

export function cohortFlagCallProblem(
    cohort: Pick<CohortType, 'is_static' | 'filters' | 'experiment_set'>
): FlagCallCriterionProblem | null {
    const criteria = cohort.filters?.properties
    if (cohortSkipsFlagCallCheck(cohort) || !criteria) {
        return null
    }
    return firstGroupProblem(criteria)
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
