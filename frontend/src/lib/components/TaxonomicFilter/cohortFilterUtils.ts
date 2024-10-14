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
                const nestedCohort = allCohorts.find((item) => item.id === value.value_property)
                return nestedCohort ? hasBehavioralFilter(nestedCohort, allCohorts) : false
            }
            return false
        })
    }

    return cohort.filters?.properties ? checkCriteriaGroup(cohort.filters.properties) : false
}

export const filterNonBehavioralCohorts = (items: CohortType[], hideBehavioralCohorts?: boolean): CohortType[] => {
    if (!hideBehavioralCohorts) {
        return items
    }

    return items.filter((item) => !hasBehavioralFilter(item, items))
}
