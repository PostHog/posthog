import { BehavioralFilterKey } from 'scenes/cohorts/CohortFilters/types'

import { AnyCohortCriteriaType, CohortCriteriaGroupFilter, CohortType } from '~/types'

function isCohortCriteriaGroupFilter(
    value: AnyCohortCriteriaType | CohortCriteriaGroupFilter
): value is CohortCriteriaGroupFilter {
    return (value as CohortCriteriaGroupFilter).type === 'AND' || (value as CohortCriteriaGroupFilter).type === 'OR'
}

const hasBehavioralFilter = (cohort: CohortType, allCohorts: CohortType[]): boolean => {
    const checkCriteriaGroup = (group: CohortCriteriaGroupFilter): boolean => {
        return group.values.some((value) => {
            if (isCohortCriteriaGroupFilter(value)) {
                return checkCriteriaGroup(value)
            }
            if (value.type === BehavioralFilterKey.Behavioral) {
                return true
            }
            if (value.type === BehavioralFilterKey.Cohort) {
                // the first time we load the page we haven't transformed the cohort data,
                // so there's no value_property, and we need to use `value.value` instead.
                const cohortId = value.value_property || value.value
                const nestedCohort = allCohorts.find((item) => item.id === cohortId)
                if (nestedCohort) {
                    return hasBehavioralFilter(nestedCohort, allCohorts)
                }
                return false
            }
            return false
        })
    }

    return cohort.filters?.properties ? checkCriteriaGroup(cohort.filters.properties) : false
}

export const filterOutBehavioralCohorts = (items: CohortType[], hideBehavioralCohorts?: boolean): CohortType[] => {
    if (!hideBehavioralCohorts) {
        return items
    }

    return items.filter((item) => !hasBehavioralFilter(item, items))
}
