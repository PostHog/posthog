import {
    AnyCohortCriteriaType,
    AnyCohortGroupType,
    BehavioralCohortType,
    BehavioralEventType,
    BehavioralLifecycleType,
    CohortCriteriaGroupFilter,
    CohortCriteriaType,
    CohortGroupType,
    CohortType,
    FilterLogicalOperator,
    TimeUnitType,
} from '~/types'
import { ENTITY_MATCH_TYPE, PROPERTY_MATCH_TYPE } from 'lib/constants'
import { BehavioralFilterKey, BehavioralFilterType, FieldWithFieldKey } from 'scenes/cohorts/CohortFilters/types'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { convertPropertyGroupToProperties } from 'lib/utils'
import { DeepPartialMap, ValidationErrorType } from 'kea-forms'
import equal from 'fast-deep-equal'
import { CRITERIA_VALIDATIONS, ROWS } from 'scenes/cohorts/CohortFilters/constants'

export function cleanBehavioralTypeCriteria(criteria: AnyCohortCriteriaType): AnyCohortCriteriaType {
    let type = undefined
    if (
        [
            BehavioralEventType.PerformEvent,
            BehavioralEventType.PerformMultipleEvents,
            BehavioralEventType.PerformSequenceEvents,
            BehavioralEventType.NotPerformSequenceEvents,
            BehavioralEventType.HaveProperty,
            BehavioralEventType.NotHaveProperty,
        ].includes(criteria.value as BehavioralEventType)
    ) {
        type = BehavioralFilterKey.Behavioral
    }
    if (
        [BehavioralCohortType.InCohort, BehavioralCohortType.NotInCohort].includes(
            criteria.value as BehavioralCohortType
        )
    ) {
        type = BehavioralFilterKey.Behavioral
    }
    if (
        [
            BehavioralLifecycleType.PerformEventFirstTime,
            BehavioralLifecycleType.PerformEventRegularly,
            BehavioralLifecycleType.StopPerformEvent,
            BehavioralLifecycleType.StartPerformEventAgain,
        ].includes(criteria.value as BehavioralLifecycleType)
    ) {
        type = BehavioralFilterKey.Behavioral
    }
    return {
        ...criteria,
        ...(type ? { type } : {}),
    }
}

export function isCohortCriteriaGroup(
    criteria:
        | CohortCriteriaGroupFilter
        | AnyCohortCriteriaType[]
        | AnyCohortCriteriaType
        | AnyCohortGroupType[]
        | AnyCohortGroupType
        | undefined
): criteria is CohortCriteriaGroupFilter {
    if (criteria) {
        return (
            (criteria as CohortCriteriaGroupFilter).type !== undefined &&
            (criteria as CohortCriteriaGroupFilter).values !== undefined
        )
    }
    return false
}

export function isValidCohortGroup(criteria: AnyCohortGroupType): boolean {
    return !(
        (criteria.matchType === PROPERTY_MATCH_TYPE && !criteria.properties?.length) ||
        (criteria.matchType === ENTITY_MATCH_TYPE && !(criteria.action_id || criteria.event_id))
    )
}

export function createCohortFormData(cohort: CohortType): FormData {
    const rawCohort = {
        ...cohort,
        groups: JSON.stringify(
            cohort.is_static
                ? []
                : cohort.groups.map((group: CohortGroupType) => ({ ...group, id: undefined, matchType: undefined }))
        ),
    }
    // Must use FormData to encode file binary in request
    const cohortFormData = new FormData()
    for (const [itemKey, value] of Object.entries(rawCohort)) {
        cohortFormData.append(itemKey, value as string | Blob)
    }
    return cohortFormData
}

export function addLocalCohortGroupId(group: Partial<CohortGroupType>): CohortGroupType {
    const matchType = group.action_id || group.event_id ? ENTITY_MATCH_TYPE : PROPERTY_MATCH_TYPE

    return {
        matchType,
        id: Math.random().toString().substr(2, 5),
        ...group,
    }
}

export function processCohortOnSet(cohort: CohortType, isGroup: boolean = false): CohortType {
    return {
        ...cohort,
        ...(isGroup
            ? {
                  filters: {
                      properties: cohort.filters.properties,
                  },
              }
            : {
                  groups:
                      cohort.groups?.map((group) => ({
                          ...addLocalCohortGroupId(group),
                          ...(group.properties
                              ? { properties: convertPropertyGroupToProperties(group.properties) }
                              : {}),
                      })) ?? [],
              }),
    }
}

export const NEW_CRITERIA = {
    type: BehavioralFilterKey.Behavioral,
    value: BehavioralEventType.PerformEvent,
    event_type: TaxonomicFilterGroupType.Events,
    time_value: 30,
    time_interval: TimeUnitType.Day,
}

export const NEW_CRITERIA_GROUP: CohortCriteriaGroupFilter = {
    id: Math.random().toString().substr(2, 5),
    type: FilterLogicalOperator.Or,
    values: [NEW_CRITERIA],
}

export const NEW_COHORT: CohortType = {
    id: 'new',
    groups: [
        {
            id: Math.random().toString().substr(2, 5),
            matchType: PROPERTY_MATCH_TYPE,
            properties: [],
        },
    ],
    filters: {
        properties: {
            id: Math.random().toString().substr(2, 5),
            type: FilterLogicalOperator.Or,
            values: [NEW_CRITERIA_GROUP],
        },
    },
}

export function validateGroup(
    group: CohortCriteriaGroupFilter | AnyCohortCriteriaType
): DeepPartialMap<CohortCriteriaGroupFilter, ValidationErrorType> {
    if (!isCohortCriteriaGroup(group)) {
        return {}
    }

    // Validate at highest level first (groups and then criteria)
    const criteria = (group.values as AnyCohortCriteriaType[])
        .filter((g) => !isCohortCriteriaGroup(g))
        .map((c, index) => ({ ...c, index }))
    const negatedCriteria = criteria.filter((c) => !!c.negation)

    console.log('CHECK 1', criteria, negatedCriteria, criteria)

    if (
        // Negation criteria can only be used when matching ALL criteria
        (group.type !== FilterLogicalOperator.And && negatedCriteria.length > 0) ||
        // Negation criteria has at least one positive matching criteria
        (group.type === FilterLogicalOperator.And && negatedCriteria.length === criteria.length)
    ) {
        return {
            id: 'Negation criteria are only supported after you have specified at least one positive matching criteria. Negation criteria can only be used when matching all criteria (AND).',
        }
    }

    console.log('CHECK 2', criteria)

    // Negation where matching criteria cancel each other out
    const negatedFailingCriteriaIndices = new Set()
    negatedCriteria.forEach((negatedC) => {
        const baseCriteria = { ...negatedC }
        delete baseCriteria.negation
        criteria.forEach((c) => {
            if (
                equal(Object.assign({}, baseCriteria, { index: undefined }), Object.assign({}, c, { index: undefined }))
            ) {
                negatedFailingCriteriaIndices.add(c.index)
                negatedFailingCriteriaIndices.add(baseCriteria.index)
            }
        })
    })
    if (
        group.type === FilterLogicalOperator.And &&
        negatedCriteria.length > 0 &&
        negatedFailingCriteriaIndices.size > 0
    ) {
        return {
            id: 'These criteria cancel each other out, and would result in no matching persons.',
            values: criteria.map((c) => ({
                value: negatedFailingCriteriaIndices.has(c)
                    ? 'These criteria cancel each other out, and would result in no matching persons.'
                    : undefined,
            })) as DeepPartialMap<CohortCriteriaType, ValidationErrorType>[],
        }
    }

    console.log('CHECK 3', negatedCriteria, negatedFailingCriteriaIndices)

    // Specific criteria value scenarios
    if (criteria.some((c) => c.value === BehavioralLifecycleType.PerformEventRegularly)) {
        return {
            values: criteria.map((c) =>
                c.value === BehavioralLifecycleType.PerformEventRegularly
                    ? (c.min_periods ?? 0) > (c.total_periods ?? 0)
                        ? {
                              id: 'The lowerbound period value must not be greater than the upperbound value.',
                              min_periods: 'The lowerbound period value must not be greater than the upperbound value.',
                              total_periods:
                                  'The lowerbound period value must not be greater than the upperbound value.',
                          }
                        : {}
                    : {}
            ) as DeepPartialMap<CohortCriteriaType, ValidationErrorType>[],
        }
    }

    console.log('CHECK 4', criteria)

    // Generic criteria values cannot be empty
    return {
        values: criteria.map((c) => {
            if (!c.value) {
                return {}
            }
            const requiredFields = ROWS[c.value].fields.filter((f) => !!f.fieldKey) as FieldWithFieldKey[]
            return Object.fromEntries(
                requiredFields.map(({ fieldKey, type }) => [
                    fieldKey,
                    c[fieldKey] !== undefined && c[fieldKey] !== null ? undefined : CRITERIA_VALIDATIONS?.[type],
                ])
            )
        }),
    }
}

export function criteriaToBehavioralFilterType(criteria: AnyCohortCriteriaType): BehavioralFilterType {
    if (criteria.negation) {
        if (criteria.value === BehavioralEventType.PerformSequenceEvents) {
            return BehavioralEventType.NotPerformSequenceEvents
        }
        if (criteria.value === BehavioralEventType.PerformEvent) {
            return BehavioralEventType.NotPerformedEvent
        }
        if (criteria.value === BehavioralEventType.HaveProperty) {
            return BehavioralEventType.NotHaveProperty
        }
        if (criteria.value === BehavioralCohortType.InCohort) {
            return BehavioralCohortType.NotInCohort
        }
    }
    return criteria.value ?? BehavioralEventType.PerformEvent
}

export function behavioralFilterTypeToCriteria(value: BehavioralFilterType): AnyCohortCriteriaType {
    if (value === BehavioralEventType.NotPerformSequenceEvents) {
        return {
            type: BehavioralFilterKey.Behavioral,
            value: BehavioralEventType.PerformSequenceEvents,
            negation: true,
        }
    }
    if (value === BehavioralEventType.NotPerformedEvent) {
        return {
            type: BehavioralFilterKey.Behavioral,
            value: BehavioralEventType.PerformEvent,
            negation: true,
        }
    }
    if (value === BehavioralEventType.NotHaveProperty) {
        return {
            type: BehavioralFilterKey.Behavioral,
            value: BehavioralEventType.HaveProperty,
            negation: true,
        }
    }
    if (value === BehavioralCohortType.NotInCohort) {
        return {
            type: BehavioralFilterKey.Cohort,
            value: BehavioralCohortType.InCohort,
            negation: true,
        }
    }

    return {
        value,
        negation: false,
    }
}
