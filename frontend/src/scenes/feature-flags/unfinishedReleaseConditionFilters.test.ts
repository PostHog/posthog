import { AnyPropertyFilter, FeatureFlagGroupType, PropertyFilterType, PropertyOperator } from '~/types'

import { findDroppableFilters, withoutFilters } from './unfinishedReleaseConditionFilters'

function person(key: string, value: AnyPropertyFilter['value']): AnyPropertyFilter {
    return { key, value, operator: PropertyOperator.Exact, type: PropertyFilterType.Person } as AnyPropertyFilter
}

function group(...properties: AnyPropertyFilter[]): FeatureFlagGroupType {
    return { properties, rollout_percentage: 100, variant: null }
}

describe('findDroppableFilters', () => {
    test.each([
        {
            name: 'drops a new row with no value next to a finished filter',
            groups: [group(person('email', ['a@example.com']), person('plan', null))],
            saved: [group(person('email', ['a@example.com']))],
            expected: [[1]],
        },
        {
            name: 'drops a new row with an empty value list',
            groups: [group(person('email', ['a@example.com']), person('plan', []))],
            saved: undefined,
            expected: [[1]],
        },
        {
            name: 'keeps a row whose property the saved flag filters on',
            groups: [group(person('email', ['a@example.com']), person('plan', []))],
            saved: [group(person('plan', ['free']))],
            expected: [[]],
        },
        {
            name: 'keeps the last filter in a condition set',
            groups: [group(person('plan', null))],
            saved: undefined,
            expected: [[]],
        },
        {
            name: 'keeps every row when all rows in the set have no value',
            groups: [group(person('plan', null), person('country', null))],
            saved: undefined,
            expected: [[]],
        },
    ])('$name', ({ groups, saved, expected }) => {
        expect(findDroppableFilters(groups, saved)).toEqual(expected)
    })

    it('removes only the droppable rows', () => {
        const groups = [group(person('email', ['a@example.com']), person('plan', null))]
        expect(withoutFilters(groups, findDroppableFilters(groups, undefined))).toEqual([
            group(person('email', ['a@example.com'])),
        ])
    })
})
