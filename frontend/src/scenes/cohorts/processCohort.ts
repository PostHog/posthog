import { v4 as uuidv4 } from 'uuid'

import { COHORT_EVENT_TYPES_WITH_EXPLICIT_DATETIME } from 'scenes/cohorts/CohortFilters/constants'
import { BehavioralFilterKey } from 'scenes/cohorts/CohortFilters/types'

import {
    AnyCohortCriteriaType,
    BehavioralCohortType,
    BehavioralEventType,
    CohortCriteriaGroupFilter,
    CohortType,
    FilterLogicalOperator,
} from '~/types'

export function processCohort(cohort: CohortType): CohortType {
    return {
        ...cohort,

        /* Populate value_property with value and overwrite value with corresponding behavioral filter type */
        filters: {
            properties: {
                ...cohort.filters.properties,
                values: (cohort.filters.properties?.values?.map((group) =>
                    'values' in group
                        ? {
                              ...group,
                              values: (group.values as AnyCohortCriteriaType[]).map((c) => processCohortCriteria(c)),
                              sort_key: uuidv4(),
                          }
                        : // Wrap flat API criteria (no nested `values` array) into a group
                          // so CohortCriteriaGroups can render them via isCohortCriteriaGroup()
                          {
                              type: FilterLogicalOperator.And,
                              values: [processCohortCriteria(group as AnyCohortCriteriaType)],
                              sort_key: uuidv4(),
                          }
                ) ?? []) as CohortCriteriaGroupFilter[] | AnyCohortCriteriaType[],
            },
        },
    }
}

function convertTimeValueToRelativeTime(criteria: AnyCohortCriteriaType): string | undefined {
    const timeValue = criteria?.time_value
    const timeInterval = criteria?.time_interval

    if (timeValue && timeInterval) {
        return `-${timeValue}${timeInterval[0]}`
    }
}

// Mirrors BEHAVIORAL_VALUE_ALIASES in posthog/models/property/property.py: values older cohort
// builders stored that the backend still resolves to a canonical behavioral type. The API hands
// them back verbatim, so without this the frontend treats them as unmapped and renders no fields.
// A Map, not an object literal: a stored value of 'constructor' or 'toString' resolves to an
// Object.prototype member on a plain lookup.
const BEHAVIORAL_VALUE_ALIASES = new Map<string, BehavioralEventType>([
    ['performed_event_multiple_times', BehavioralEventType.PerformMultipleEvents],
])

function processCohortCriteria(criteria: AnyCohortCriteriaType): AnyCohortCriteriaType {
    if (!criteria.type) {
        return criteria
    }

    const processedCriteria = { ...criteria }

    if (criteria.type === BehavioralFilterKey.Behavioral && typeof criteria.value === 'string') {
        processedCriteria.value = BEHAVIORAL_VALUE_ALIASES.get(criteria.value) ?? criteria.value
    }

    if (
        [BehavioralFilterKey.Cohort, BehavioralFilterKey.Person, BehavioralFilterKey.PersonMetadata].includes(
            criteria.type
        ) &&
        !('value_property' in criteria)
    ) {
        processedCriteria.value_property = criteria.value
        processedCriteria.value =
            criteria.type === BehavioralFilterKey.Cohort
                ? BehavioralCohortType.InCohort
                : BehavioralEventType.HaveProperty
    }

    if (
        [BehavioralFilterKey.Behavioral].includes(criteria.type) &&
        !('explicit_datetime' in criteria) &&
        processedCriteria.value &&
        COHORT_EVENT_TYPES_WITH_EXPLICIT_DATETIME.includes(processedCriteria.value)
    ) {
        processedCriteria.explicit_datetime = convertTimeValueToRelativeTime(criteria)
    }

    if (processedCriteria.sort_key == null) {
        processedCriteria.sort_key = uuidv4()
    }

    return processedCriteria
}
