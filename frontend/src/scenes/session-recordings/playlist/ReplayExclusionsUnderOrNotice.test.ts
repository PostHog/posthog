import {
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    RecordingUniversalFilters,
    UniversalFiltersGroupValue,
} from '~/types'

import { isAffectedByReplayExclusionsUnderOrChange } from './ReplayExclusionsUnderOrNotice'

const filters = (
    type: FilterLogicalOperator,
    values: UniversalFiltersGroupValue[],
    innerType: FilterLogicalOperator = type
): RecordingUniversalFilters =>
    ({ filter_group: { type, values: [{ type: innerType, values }] } }) as RecordingUniversalFilters

const pageview: UniversalFiltersGroupValue = { id: '$pageview', name: '$pageview', type: 'events' }
const emailNotSet: UniversalFiltersGroupValue = {
    key: 'email',
    type: PropertyFilterType.Person,
    operator: PropertyOperator.IsNotSet,
    value: 'is_not_set',
}
const emailSet: UniversalFiltersGroupValue = {
    key: 'email',
    type: PropertyFilterType.Person,
    operator: PropertyOperator.IsSet,
    value: 'is_set',
}

describe('isAffectedByReplayExclusionsUnderOrChange', () => {
    it.each<[string, RecordingUniversalFilters, boolean]>([
        // Under OR any negative filter changes from a match to an exclusion
        ['OR with a negative person property', filters(FilterLogicalOperator.Or, [pageview, emailNotSet]), true],
        [
            'OR with a negated event',
            filters(FilterLogicalOperator.Or, [pageview, { ...pageview, id: '$autocapture', negation: true }]),
            true,
        ],
        [
            'OR with a negative property on an event',
            filters(FilterLogicalOperator.Or, [
                {
                    ...pageview,
                    properties: [
                        {
                            key: '$pathname',
                            type: PropertyFilterType.Event as const,
                            operator: PropertyOperator.NotIContains,
                            value: 'other',
                        },
                    ],
                },
            ]),
            true,
        ],
        [
            'OR with a NOT IN cohort',
            filters(FilterLogicalOperator.Or, [
                { key: 'id', type: PropertyFilterType.Cohort, operator: PropertyOperator.NotIn, value: 1 },
            ]),
            true,
        ],
        // The effective operand is OR when any nested group is OR, in the same way as deriveOperand
        [
            'AND outer group with an OR inner group and a negative filter',
            filters(FilterLogicalOperator.And, [emailNotSet], FilterLogicalOperator.Or),
            true,
        ],
        // Under AND the exclusion paths were already on, so nothing changes
        ['AND with a negative person property', filters(FilterLogicalOperator.And, [pageview, emailNotSet]), false],
        // Without a negative filter there is nothing to exclude
        ['OR with only positive filters', filters(FilterLogicalOperator.Or, [pageview, emailSet]), false],
        ['OR with no filters', filters(FilterLogicalOperator.Or, []), false],
    ])('%s', (_name, input, expected) => {
        expect(isAffectedByReplayExclusionsUnderOrChange(input)).toBe(expected)
    })
})
