import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import { filterLeaves, removeFilterLeaf } from './filterChipLeaves'

const leaf = (key: string): any => ({
    key,
    value: '1',
    operator: PropertyOperator.Exact,
    type: PropertyFilterType.Event,
})

const group: UniversalFiltersGroup = {
    type: FilterLogicalOperator.And,
    values: [{ type: FilterLogicalOperator.And, values: [leaf('a'), leaf('b')] }, leaf('c')],
}

describe('filter chips', () => {
    it('lists every condition with its path through the nested groups', () => {
        expect(filterLeaves(group).map((l) => [l.path, (l.filter as { key?: string }).key])).toEqual([
            [[0, 0], 'a'],
            [[0, 1], 'b'],
            [[1], 'c'],
        ])
    })

    it.each([
        { name: 'a nested leaf', path: [0, 1], remaining: ['a', 'c'], rootValues: 2 },
        { name: 'a root leaf', path: [1], remaining: ['a', 'b'], rootValues: 1 },
        { name: 'a leaf inside a group, keeping the group', path: [0, 0], remaining: ['b', 'c'], rootValues: 2 },
    ])('removes $name', ({ path, remaining, rootValues }) => {
        const next = removeFilterLeaf(group, path)
        expect(filterLeaves(next).map((l) => (l.filter as { key?: string }).key)).toEqual(remaining)
        expect(next.values.length).toBe(rootValues)
    })
})
