import {
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
} from 'lib/components/TaxonomicFilter/types'

import { PropertyFilterType, PropertyOperator } from '~/types'

import {
    filterPinnedForContext,
    filterRecentsForContext,
    pinnedItemMatchesSearch,
    recentItemMatchesSearch,
} from './suggestedContextFilters'

const recent = (
    sourceGroupType: TaxonomicFilterGroupType,
    name: string,
    extra: Record<string, any> = {}
): TaxonomicDefinitionTypes =>
    ({
        name,
        _recentContext: { sourceGroupType, sourceGroupName: sourceGroupType, sourceValue: name, ...extra },
    }) as unknown as TaxonomicDefinitionTypes

const pinned = (sourceGroupType: TaxonomicFilterGroupType, name: string): TaxonomicDefinitionTypes =>
    ({
        name,
        _pinnedContext: { sourceGroupType, sourceGroupName: sourceGroupType, value: name },
    }) as unknown as TaxonomicDefinitionTypes

const groupsWithGetName = (types: TaxonomicFilterGroupType[]): TaxonomicFilterGroup[] =>
    types.map(
        (type) =>
            ({
                type,
                getName: (item: TaxonomicDefinitionTypes) => ('name' in item ? item.name : ''),
            }) as TaxonomicFilterGroup
    )

describe('suggestedContextFilters', () => {
    describe('filterRecentsForContext', () => {
        it('keeps recents whose source group is visible and drops the rest', () => {
            const items = [
                recent(TaxonomicFilterGroupType.Events, 'in'),
                recent(TaxonomicFilterGroupType.Cohorts, 'out'),
            ]
            const result = filterRecentsForContext(items, [
                TaxonomicFilterGroupType.Events,
                TaxonomicFilterGroupType.PersonProperties,
            ])
            expect(result.map((i) => ('name' in i ? i.name : ''))).toEqual(['in'])
        })

        it('drops recents whose operator is excluded for their group', () => {
            const items = [
                recent(TaxonomicFilterGroupType.EventProperties, 'keep', {
                    propertyFilter: { operator: PropertyOperator.Exact },
                }),
                recent(TaxonomicFilterGroupType.EventProperties, 'drop', {
                    propertyFilter: { operator: PropertyOperator.IContains },
                }),
            ]
            const result = filterRecentsForContext(items, [TaxonomicFilterGroupType.EventProperties], {
                [TaxonomicFilterGroupType.EventProperties]: [PropertyOperator.IContains],
            })
            expect(result.map((i) => ('name' in i ? i.name : ''))).toEqual(['keep'])
        })

        it('dedupes by storage key and strips the property filter when selecting a key only', () => {
            const items = [
                recent(TaxonomicFilterGroupType.EventProperties, 'dup', {
                    propertyFilter: { operator: PropertyOperator.Exact, value: 'a' },
                }),
                recent(TaxonomicFilterGroupType.EventProperties, 'dup', {
                    propertyFilter: { operator: PropertyOperator.Exact, value: 'b' },
                }),
            ]
            const result = filterRecentsForContext(items, [TaxonomicFilterGroupType.EventProperties], undefined, true)
            expect(result).toHaveLength(1)
            expect((result[0] as any)._recentContext.propertyFilter).toBeUndefined()
        })
    })

    describe('filterPinnedForContext', () => {
        it('keeps pinned whose source group is visible and drops the rest', () => {
            const items = [
                pinned(TaxonomicFilterGroupType.Events, 'in'),
                pinned(TaxonomicFilterGroupType.Cohorts, 'out'),
            ]
            const result = filterPinnedForContext(items, [TaxonomicFilterGroupType.Events])
            expect(result.map((i) => ('name' in i ? i.name : ''))).toEqual(['in'])
        })
    })

    describe('recentItemMatchesSearch', () => {
        const groups = groupsWithGetName([TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.EventProperties])

        it.each([
            { query: 'page', name: 'pageview', expected: true },
            { query: 'zzz', name: 'pageview', expected: false },
        ])('matches on source-group name ($query -> $expected)', ({ query, name, expected }) => {
            expect(recentItemMatchesSearch(recent(TaxonomicFilterGroupType.Events, name), query, groups)).toBe(expected)
        })

        it('matches on the recorded property filter label', () => {
            const item = recent(TaxonomicFilterGroupType.EventProperties, 'no-name-match', {
                propertyFilter: {
                    type: PropertyFilterType.Event,
                    key: 'my_custom_prop',
                    operator: PropertyOperator.Exact,
                    value: 'google',
                },
            })
            expect(recentItemMatchesSearch(item, 'my_custom_prop', groups)).toBe(true)
        })

        it('returns false for items without recent context', () => {
            expect(recentItemMatchesSearch({ name: 'x' } as TaxonomicDefinitionTypes, 'x', groups)).toBe(false)
        })
    })

    describe('pinnedItemMatchesSearch', () => {
        const groups = groupsWithGetName([TaxonomicFilterGroupType.Events])

        it.each([
            { query: 'page', expected: true },
            { query: 'zzz', expected: false },
        ])('matches on source-group name ($query -> $expected)', ({ query, expected }) => {
            expect(pinnedItemMatchesSearch(pinned(TaxonomicFilterGroupType.Events, 'pageview'), query, groups)).toBe(
                expected
            )
        })
    })
})
