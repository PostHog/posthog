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
import {ENTITY_MATCH_TYPE, PROPERTY_MATCH_TYPE} from 'lib/constants'
import {BehavioralFilterKey, BehavioralFilterType, FieldWithFieldKey} from 'scenes/cohorts/CohortFilters/types'
import {TaxonomicFilterGroupType} from 'lib/components/TaxonomicFilter/types'
import {convertPropertyGroupToProperties} from 'lib/utils'
import {DeepPartialMap, ValidationErrorType} from 'kea-forms'
import equal from 'fast-deep-equal'
import {CRITERIA_VALIDATIONS, ROWS} from 'scenes/cohorts/CohortFilters/constants'

export function cleanBehavioralTypeCriteria(criteria: AnyCohortCriteriaType): AnyCohortCriteriaType {
    let type = undefined
    if (
        [
            BehavioralEventType.PerformEvent,
            BehavioralEventType.PerformMultipleEvents,
            BehavioralEventType.PerformSequenceEvents,
            BehavioralEventType.NotPerformSequenceEvents,
            BehavioralLifecycleType.PerformEventFirstTime,
            BehavioralLifecycleType.PerformEventRegularly,
            BehavioralLifecycleType.StopPerformEvent,
            BehavioralLifecycleType.StartPerformEventAgain,
        ].includes(criteria.value as BehavioralEventType | BehavioralLifecycleType)
    ) {
        type = BehavioralFilterKey.Behavioral
    }
    if (
        [BehavioralCohortType.InCohort, BehavioralCohortType.NotInCohort].includes(
            criteria.value as BehavioralCohortType
        )
    ) {
        type = BehavioralFilterKey.Cohort
    }
    if (
        [
            BehavioralEventType.HaveProperty,
            BehavioralEventType.NotHaveProperty,
        ].includes(criteria.value as BehavioralEventType)
    ) {
        type = BehavioralFilterKey.Person
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

export function createCohortFormData(cohort: CohortType, isNewCohortFilterEnabled: boolean = false): FormData {
    const rawCohort = {
        ...(cohort.name ? {name: cohort.name} : {}),
        ...(cohort.description ? {description: cohort.description} : {}),
        ...(cohort.csv ? {csv: cohort.csv} : {}),
        ...(cohort.is_static ? {is_static: cohort.is_static} : {}),
        created_by: JSON.stringify(cohort.created_by),
        ...(isNewCohortFilterEnabled
            ? {
                  filters: JSON.stringify(cohort.is_static ? {} : cohort.filters),
                  groups: JSON.stringify([]),
              }
            : {
                  filters: undefined,
                  groups: JSON.stringify(
                      cohort.is_static
                          ? []
                          : cohort.groups.map((group: CohortGroupType) => ({
                                ...group,
                                id: undefined,
                                matchType: undefined,
                            }))
                  ),
              }),
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
    time_value: "30",
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

    // Negation where matching criteria cancel each other out
    const negatedFailingCriteriaIndices = new Set()
    negatedCriteria.forEach((negatedC) => {
        const baseCriteria = { ...negatedC }
        criteria.forEach((c) => {
            if (
                baseCriteria.index !== c.index &&
                equal(Object.assign({}, baseCriteria, { index: undefined }), Object.assign({}, c, { index: undefined, negation: !c.negation }))
            ) {
                negatedFailingCriteriaIndices.add(c.index)
                negatedFailingCriteriaIndices.add(baseCriteria.index)
            }
        })
    })

    console.log("CHECK", group, negatedCriteria, negatedFailingCriteriaIndices)

    if (
        group.type === FilterLogicalOperator.And &&
        negatedCriteria.length > 0 &&
        negatedFailingCriteriaIndices.size > 0
    ) {
        return {
            id: 'These criteria cancel each other out, and would result in no matching persons.',
            values: criteria.map((c) => ({
                value: negatedFailingCriteriaIndices.has(c.index)
                    ? 'These criteria cancel each other out, and would result in no matching persons.'
                    : undefined,
            })) as DeepPartialMap<CohortCriteriaType, ValidationErrorType>[],
        }
    }

    // Specific criteria value scenarios
    const regularEventCriteria = criteria.filter((c) => c.value === BehavioralLifecycleType.PerformEventRegularly)
    if (
        regularEventCriteria.length > 0 &&
        regularEventCriteria.every((c) => typeof c.min_periods === 'number' && typeof c.total_periods === 'number')
    ) {
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

    // Generic criteria values cannot be empty
    return {
        values: criteria.map((c) => {
            const requiredFields = ROWS[criteriaToBehavioralFilterType(c)].fields.filter(
                (f) => !!f.fieldKey
            ) as FieldWithFieldKey[]
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
        if (criteria.type === BehavioralFilterKey.Person) {
            return BehavioralEventType.NotHaveProperty
        }
        if (criteria.type === BehavioralFilterKey.Cohort) {
            return BehavioralCohortType.NotInCohort
        }
    }
    return criteria.value ?? BehavioralEventType.PerformEvent
}

export function determineFilterType(
    type: BehavioralFilterKey,
    value: BehavioralFilterType,
    negation: boolean = false
): AnyCohortCriteriaType {
    if (value === BehavioralEventType.NotPerformSequenceEvents || (value === BehavioralEventType.PerformSequenceEvents && negation)) {
        return {
            type: BehavioralFilterKey.Behavioral,
            value: BehavioralEventType.PerformSequenceEvents,
            negation: true,
        }
    }
    if (value === BehavioralEventType.NotPerformedEvent || (value === BehavioralEventType.PerformEvent && negation)) {
        return {
            type: BehavioralFilterKey.Behavioral,
            value: BehavioralEventType.PerformEvent,
            negation: true,
        }
    }
    if (value === BehavioralCohortType.NotInCohort || (value === BehavioralCohortType.InCohort && negation)) {
        return {
            type: BehavioralFilterKey.Cohort,
            value: BehavioralCohortType.InCohort,
            negation: true,
        }
    }
    if (value === BehavioralEventType.NotHaveProperty || (value === BehavioralEventType.HaveProperty && negation)) {
        return {
            type: BehavioralFilterKey.Person,
            value: BehavioralEventType.HaveProperty,
            negation: true,
        }
    }

    return {
        type,
        value,
        negation: false,
    }
}

export function resolveCohortFieldValue(criteria: AnyCohortCriteriaType, fieldKey: string): string | number | boolean | null | undefined {
    // Resolve correct behavioral filter type
    if (fieldKey === 'value') {
        return criteriaToBehavioralFilterType(criteria)
    }
    return criteria?.[fieldKey] ?? null
}