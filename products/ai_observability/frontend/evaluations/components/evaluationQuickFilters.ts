import { objectsEqual } from 'lib/utils/objects'

import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import type { EvaluationConditionSet } from '../types'

export type QuickFilterKey = 'internal' | 'errors' | 'expensive' | 'sample'

const QUICK_SAMPLE_PERCENTAGE = 10

const ERRORS_FILTER: AnyPropertyFilter = {
    type: PropertyFilterType.Event,
    key: '$ai_is_error',
    operator: PropertyOperator.Exact,
    value: ['true'],
}

const EXPENSIVE_FILTER: AnyPropertyFilter = {
    type: PropertyFilterType.Event,
    key: '$ai_total_cost_usd',
    operator: PropertyOperator.GreaterThan,
    value: 0.01,
}

/** The team's internal and test user filters that a condition set can hold. Triggers take event and person properties only. */
export function internalUserFilters(testAccountFilters: AnyPropertyFilter[]): AnyPropertyFilter[] {
    return testAccountFilters.filter(
        (filter) => filter.type === PropertyFilterType.Event || filter.type === PropertyFilterType.Person
    )
}

function filtersFor(key: QuickFilterKey, testAccountFilters: AnyPropertyFilter[]): AnyPropertyFilter[] {
    switch (key) {
        case 'internal':
            return internalUserFilters(testAccountFilters)
        case 'errors':
            return [ERRORS_FILTER]
        case 'expensive':
            return [EXPENSIVE_FILTER]
        case 'sample':
            return []
    }
}

const hasFilter = (condition: EvaluationConditionSet, filter: AnyPropertyFilter): boolean =>
    (condition.properties ?? []).some((existing) => objectsEqual(existing, filter))

/** Whether every condition set already has what the quick filter adds. */
export function quickFilterApplied(
    key: QuickFilterKey,
    conditions: EvaluationConditionSet[],
    testAccountFilters: AnyPropertyFilter[]
): boolean {
    if (key === 'sample') {
        return conditions.every((condition) => condition.rollout_percentage === QUICK_SAMPLE_PERCENTAGE)
    }
    const filters = filtersFor(key, testAccountFilters)
    return (
        filters.length > 0 && conditions.every((condition) => filters.every((filter) => hasFilter(condition, filter)))
    )
}

/** Adds the quick filter to every condition set, so it holds whichever set matches. */
export function applyQuickFilter(
    key: QuickFilterKey,
    conditions: EvaluationConditionSet[],
    testAccountFilters: AnyPropertyFilter[]
): EvaluationConditionSet[] {
    if (key === 'sample') {
        return conditions.map((condition) => ({ ...condition, rollout_percentage: QUICK_SAMPLE_PERCENTAGE }))
    }
    const filters = filtersFor(key, testAccountFilters)
    return conditions.map((condition) => ({
        ...condition,
        properties: [...(condition.properties ?? []), ...filters.filter((filter) => !hasFilter(condition, filter))],
    }))
}
