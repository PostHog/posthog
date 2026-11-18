import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import type { EvaluationConditionSet } from '../types'
import { QuickFilterKey, applyQuickFilter, quickFilterApplied } from './evaluationQuickFilters'

const conditionSets = (): EvaluationConditionSet[] => [
    { id: 'a', rollout_percentage: 100, properties: [] },
    {
        id: 'b',
        rollout_percentage: 50,
        properties: [
            { type: PropertyFilterType.Event, key: '$ai_model', operator: PropertyOperator.Exact, value: ['x'] },
        ],
    },
]

const internalFilter: AnyPropertyFilter = {
    type: PropertyFilterType.Person,
    key: 'email',
    operator: PropertyOperator.NotIContains,
    value: '@example.com',
}
const cohortFilter = { type: PropertyFilterType.Cohort, key: 'id', value: 1 } as AnyPropertyFilter

describe('evaluationQuickFilters', () => {
    test.each<[QuickFilterKey, AnyPropertyFilter[], AnyPropertyFilter | null, number[]]>([
        ['internal', [internalFilter, cohortFilter], internalFilter, [100, 50]],
        [
            'errors',
            [],
            { type: PropertyFilterType.Event, key: '$ai_is_error', operator: PropertyOperator.Exact, value: ['true'] },
            [100, 50],
        ],
        [
            'expensive',
            [],
            {
                type: PropertyFilterType.Event,
                key: '$ai_total_cost_usd',
                operator: PropertyOperator.GreaterThan,
                value: 0.01,
            },
            [100, 50],
        ],
        ['sample', [], null, [10, 10]],
    ])(
        '%s reaches every condition set once, and a second click adds nothing',
        (key, testAccountFilters, added, rollouts) => {
            const once = applyQuickFilter(key, conditionSets(), testAccountFilters)
            const twice = applyQuickFilter(key, once, testAccountFilters)

            expect(quickFilterApplied(key, once, testAccountFilters)).toBe(true)
            expect(twice).toEqual(once)
            expect(once.map((set) => set.rollout_percentage)).toEqual(rollouts)
            expect(once.map((set) => set.properties?.length)).toEqual(added ? [1, 2] : [0, 1])
            once.forEach((set) => expect(set.properties).toEqual(expect.arrayContaining(added ? [added] : [])))
            expect(once.flatMap((set) => set.properties ?? [])).not.toContainEqual(cohortFilter)
        }
    )

    it('treats internal users as not set up when the team only has filters a trigger cannot hold', () => {
        expect(applyQuickFilter('internal', conditionSets(), [cohortFilter])).toEqual(conditionSets())
        expect(quickFilterApplied('internal', conditionSets(), [cohortFilter])).toBe(false)
    })
})
