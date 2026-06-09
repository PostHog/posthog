import { PropertyOperator } from '~/types'

import { TaxonomicDefinitionTypes, TaxonomicFilterGroupType } from '../types'
import { filterPinnedForContext, filterRecentsForContext } from './suggestedContextFilters'

const { Events, EventProperties, Cohorts } = TaxonomicFilterGroupType

function recent(
    sourceGroupType: TaxonomicFilterGroupType,
    name: string,
    extra: Record<string, unknown> = {}
): TaxonomicDefinitionTypes {
    return {
        name,
        _recentContext: { sourceGroupType, sourceValue: name, ...extra },
    } as unknown as TaxonomicDefinitionTypes
}

function pinned(sourceGroupType: TaxonomicFilterGroupType, name: string): TaxonomicDefinitionTypes {
    return { name, _pinnedContext: { sourceGroupType, value: name } } as unknown as TaxonomicDefinitionTypes
}

const names = (items: TaxonomicDefinitionTypes[]): string[] => items.map((i) => (i as { name: string }).name)

describe('suggestedContextFilters', () => {
    describe.each([
        ['only in-scope kept', [recent(Events, 'a'), recent(Cohorts, 'c')], [Events], ['a']],
        ['all out-of-scope dropped', [recent(Cohorts, 'c')], [Events], []],
        [
            'multiple in-scope kept in order',
            [recent(Events, 'a'), recent(EventProperties, 'b')],
            [Events, EventProperties],
            ['a', 'b'],
        ],
        ['empty input', [], [Events], []],
    ])('filterRecentsForContext — %s', (_label, items, types, expected) => {
        it('matches the expected in-scope set', () => {
            expect(names(filterRecentsForContext(items, types))).toEqual(expected)
        })
    })

    describe('filterRecentsForContext operators + key-only dedup', () => {
        it('drops a recent whose operator is excluded for its group', () => {
            const items = [recent(EventProperties, 'p', { propertyFilter: { operator: PropertyOperator.IContains } })]
            expect(
                filterRecentsForContext(items, [EventProperties], { [EventProperties]: [PropertyOperator.IContains] })
            ).toHaveLength(0)
            expect(
                filterRecentsForContext(items, [EventProperties], { [EventProperties]: [PropertyOperator.Exact] })
            ).toHaveLength(1)
        })

        it('dedups by storage key and strips the property filter when selecting a key only', () => {
            const items = [
                recent(EventProperties, 'plan', { propertyFilter: { operator: PropertyOperator.Exact } }),
                recent(EventProperties, 'plan', { propertyFilter: { operator: PropertyOperator.IContains } }),
            ]
            const out = filterRecentsForContext(items, [EventProperties], undefined, true)
            expect(out).toHaveLength(1)
            expect(
                (out[0] as unknown as { _recentContext: { propertyFilter?: unknown } })._recentContext.propertyFilter
            ).toBeUndefined()
        })
    })

    describe.each([
        ['only in-scope kept', [pinned(Events, 'a'), pinned(Cohorts, 'c')], [Events], ['a']],
        ['all out-of-scope dropped', [pinned(Cohorts, 'c')], [Events], []],
        ['empty input', [], [Events], []],
    ])('filterPinnedForContext — %s', (_label, items, types, expected) => {
        it('matches the expected in-scope set', () => {
            expect(names(filterPinnedForContext(items, types))).toEqual(expected)
        })
    })
})
