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

        it('drops a recent whose value is excluded for its group, keeping others', () => {
            const items = [recent(EventProperties, 'message'), recent(EventProperties, 'plan')]
            const out = filterRecentsForContext(items, [EventProperties], undefined, undefined, {
                [EventProperties]: ['message'],
            })
            expect(names(out)).toEqual(['plan'])
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

    describe('filterRecentsForContext bare-key expansion (value mode)', () => {
        const complete = (key: string, value: string): Record<string, unknown> => ({
            propertyFilter: { key, operator: PropertyOperator.Exact, value },
        })
        const propertyFilterOf = (item: TaxonomicDefinitionTypes): unknown =>
            (item as unknown as { _recentContext: { propertyFilter?: unknown } })._recentContext.propertyFilter

        it('prepends a bare key before a complete recent', () => {
            const out = filterRecentsForContext(
                [recent(EventProperties, 'host', complete('host', 'us'))],
                [EventProperties]
            )
            expect(names(out)).toEqual(['host', 'host'])
            expect(propertyFilterOf(out[0])).toBeUndefined()
            expect(propertyFilterOf(out[1])).toBeTruthy()
        })

        it('does not append a bare key for an incomplete recent', () => {
            expect(filterRecentsForContext([recent(EventProperties, 'host')], [EventProperties])).toHaveLength(1)
        })

        it('emits two fulls and a single bare key for two complete recents of the same key', () => {
            const out = filterRecentsForContext(
                [
                    recent(EventProperties, 'host', complete('host', 'us')),
                    recent(EventProperties, 'host', complete('host', 'eu')),
                ],
                [EventProperties]
            )
            expect(out).toHaveLength(3)
            expect(out.filter((i) => propertyFilterOf(i) === undefined)).toHaveLength(1)
        })

        it('does not expand in key-only mode', () => {
            const out = filterRecentsForContext(
                [recent(EventProperties, 'host', complete('host', 'us'))],
                [EventProperties],
                undefined,
                true
            )
            expect(out).toHaveLength(1)
            expect(propertyFilterOf(out[0])).toBeUndefined()
        })

        it('honors a per-group key-only dict: key-only group stripped, value group expanded', () => {
            const out = filterRecentsForContext(
                [recent(Cohorts, '1', complete('id', '1')), recent(EventProperties, 'host', complete('host', 'us'))],
                [Cohorts, EventProperties],
                undefined,
                { [Cohorts]: true }
            )
            const groupOf = (i: TaxonomicDefinitionTypes): TaxonomicFilterGroupType =>
                (i as unknown as { _recentContext: { sourceGroupType: TaxonomicFilterGroupType } })._recentContext
                    .sourceGroupType
            const cohortRows = out.filter((i) => groupOf(i) === Cohorts)
            const propRows = out.filter((i) => groupOf(i) === EventProperties)
            expect(cohortRows).toHaveLength(1)
            expect(propertyFilterOf(cohortRows[0])).toBeUndefined()
            expect(propRows).toHaveLength(2)
            expect(propRows.filter((i) => propertyFilterOf(i) === undefined)).toHaveLength(1)
            expect(propRows.filter((i) => propertyFilterOf(i) !== undefined)).toHaveLength(1)
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
