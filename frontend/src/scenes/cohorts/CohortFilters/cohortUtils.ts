import {
    AnyCohortCriteriaType,
    AnyCohortGroupType,
    BehavioralCohortType,
    BehavioralEventType,
    BehavioralLifecycleType,
    CohortCriteriaGroupFilter,
} from '~/types'
import { ENTITY_MATCH_TYPE, PROPERTY_MATCH_TYPE } from 'lib/constants'
import { BehavioralFilterKey } from 'scenes/cohorts/CohortFilters/types'

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
