import { TaxonomicDefinitionTypes, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { floatRecentAndPinnedToTop } from './floatRecentPinned'

describe('floatRecentAndPinnedToTop', () => {
    const G = TaxonomicFilterGroupType.Cohorts
    const keyOf = (item: TaxonomicDefinitionTypes): string | null => {
        const value = (item as { value?: string }).value
        return value == null ? null : `${G}::${value}`
    }
    const groupItem = (value: string | null): TaxonomicDefinitionTypes =>
        ({ value }) as unknown as TaxonomicDefinitionTypes
    const recent = (value: string): TaxonomicDefinitionTypes =>
        ({ _recentContext: { sourceGroupType: G, sourceValue: value } }) as unknown as TaxonomicDefinitionTypes
    const pinned = (value: string): TaxonomicDefinitionTypes =>
        ({ _pinnedContext: { sourceGroupType: G, value } }) as unknown as TaxonomicDefinitionTypes

    const valuesOf = (items: TaxonomicDefinitionTypes[]): (string | undefined)[] =>
        items.map((i) => (i as { value?: string }).value)

    it.each([
        {
            description: 'recents float to the top, most-recent (earliest in list) first',
            items: ['a', 'b', 'c', 'd'],
            recents: ['c', 'a'],
            pins: [] as string[],
            expected: ['c', 'a', 'b', 'd'],
        },
        {
            description: 'pinned float below recents, above the rest',
            items: ['a', 'b', 'c', 'd'],
            recents: ['c'],
            pins: ['b'],
            expected: ['c', 'b', 'a', 'd'],
        },
        {
            description: 'an item that is both recent and pinned appears once, in the recent tier',
            items: ['a', 'b', 'c'],
            recents: ['b'],
            pins: ['b'],
            expected: ['b', 'a', 'c'],
        },
        {
            description: 'non-matching items keep their original relative order',
            items: ['a', 'b', 'c', 'd'],
            recents: ['d'],
            pins: [] as string[],
            expected: ['d', 'a', 'b', 'c'],
        },
        {
            description: 'recent/pinned entries with no matching group item promote nothing',
            items: ['a', 'b'],
            recents: ['zzz'],
            pins: ['yyy'],
            expected: ['a', 'b'],
        },
    ])('$description', ({ items, recents, pins, expected }) => {
        const result = floatRecentAndPinnedToTop(items.map(groupItem), keyOf, recents.map(recent), pins.map(pinned))
        expect(valuesOf(result)).toEqual(expected)
    })

    it('keeps a synthetic null-value leading row (e.g. "All events") on top when a real item is pinned', () => {
        const items = [groupItem(null), groupItem('a'), groupItem('b')]
        const result = floatRecentAndPinnedToTop(items, keyOf, [], [pinned('b')])
        expect(valuesOf(result)).toEqual([null, 'b', 'a'])
    })

    it('leaves sparse-array holes in place and never keys them (a partially loaded legacy list must not crash or reorder holes)', () => {
        const throwingKeyOf = (item: TaxonomicDefinitionTypes): string | null => {
            // Mirrors a real group getValue that assumes a present item, e.g. `'id' in item`.
            const value = (item as { value?: string }).value
            return value == null ? null : `${G}::${value}`
        }
        const items: (TaxonomicDefinitionTypes | undefined)[] = [groupItem('a'), undefined, groupItem('c')]
        const result = floatRecentAndPinnedToTop(items as TaxonomicDefinitionTypes[], throwingKeyOf, [recent('c')], [])
        // 'c' floats to the top; 'a' and the hole stay in the rest tier by original index
        // (the hole is never floated and never keyed — throwingKeyOf is never called on it).
        expect(result.map((i) => (i == null ? 'HOLE' : (i as { value?: string }).value))).toEqual(['c', 'a', 'HOLE'])
    })

    it('returns the input array unchanged when there is nothing to promote', () => {
        const items = ['a', 'b'].map(groupItem)
        expect(floatRecentAndPinnedToTop(items, keyOf, [], [])).toBe(items)
    })
})
