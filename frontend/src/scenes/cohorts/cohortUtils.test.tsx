import { BehavioralFilterKey } from 'scenes/cohorts/CohortFilters/types'
import { validateGroup } from 'scenes/cohorts/cohortUtils'

import { AnyCohortCriteriaType, BehavioralEventType, CohortCriteriaGroupFilter, FilterLogicalOperator } from '~/types'

describe('validateGroup', () => {
    function groupWithNegatedCriteria(criteria: AnyCohortCriteriaType[]): CohortCriteriaGroupFilter {
        // OR group + any negated criterion triggers the "negation requires AND" error path,
        // which is the branch that builds the human-readable error from BEHAVIORAL_TYPE_TO_LABEL.
        return {
            type: FilterLogicalOperator.Or,
            values: criteria,
        }
    }

    it('falls back to the raw filter type when the label map has no matching entry', () => {
        const group = groupWithNegatedCriteria([
            {
                type: BehavioralFilterKey.Behavioral,
                // A legacy/unknown value not present in BEHAVIORAL_TYPE_TO_LABEL.
                value: 'legacy_unknown_type' as BehavioralEventType,
                negation: true,
            },
        ])

        const errors = validateGroup(group)

        expect(typeof errors.id).toBe('string')
        expect(errors.id).toContain("'legacy_unknown_type'")
        expect(errors.id).not.toContain('undefined')
    })

    it('uses the mapped label for a known behavioral filter type', () => {
        const group = groupWithNegatedCriteria([
            {
                type: BehavioralFilterKey.Behavioral,
                // Negated PerformEvent resolves to NotPerformedEvent ("Did not complete event").
                value: BehavioralEventType.PerformEvent,
                negation: true,
            },
        ])

        const errors = validateGroup(group)

        expect(errors.id).toContain("'Did not complete event'")
    })
})
