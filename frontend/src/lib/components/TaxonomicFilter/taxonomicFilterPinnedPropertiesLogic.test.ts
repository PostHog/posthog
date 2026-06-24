import { initKeaTests } from '~/test/init'

import {
    hasPinnedContext,
    pickMinimalPinnedItem,
    stripPinnedContext,
    taxonomicFilterPinnedPropertiesLogic,
} from './taxonomicFilterPinnedPropertiesLogic'
import { TaxonomicFilterGroupType } from './types'

const MIGRATION_KEY = 'taxonomicFilterPinnedProperties__migrated__default'
const OLD_PERSIST_KEY = 'scenes.session-recordings.player.playerSettingsLogic.quickFilterProperties'

describe('taxonomicFilterPinnedPropertiesLogic', () => {
    let logic: ReturnType<typeof taxonomicFilterPinnedPropertiesLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        logic = taxonomicFilterPinnedPropertiesLogic.build()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('starts with an empty list', () => {
        expect(logic.values.pinnedFilters).toEqual([])
    })

    it('togglePin stores the item with PII / heavy fields stripped', () => {
        const item = { name: '$browser', id: 'prop-1', description: 'some desc', tags: ['a'] }
        logic.actions.togglePin(TaxonomicFilterGroupType.EventProperties, 'Event properties', '$browser', item)

        const filters = logic.values.pinnedFilters
        expect(filters).toHaveLength(1)
        expect(filters[0]).toEqual(
            expect.objectContaining({
                groupType: TaxonomicFilterGroupType.EventProperties,
                groupName: 'Event properties',
                value: '$browser',
                item: { name: '$browser', id: 'prop-1', description: 'some desc', tags: ['a'] },
            })
        )
        expect(typeof filters[0].timestamp).toBe('number')
    })

    it.each([
        {
            description: 'Persons preserves distinct_ids so person.distinct_ids[0] does not throw',
            groupType: TaxonomicFilterGroupType.Persons,
            value: 'distinct-abc',
            item: { name: 'Alice', distinct_ids: ['distinct-abc', 'distinct-old'], uuid: 'u-1' },
            expectedItem: { name: 'Alice', distinct_ids: ['distinct-abc', 'distinct-old'], uuid: 'u-1' },
            getValue: (it: any) => it.distinct_ids[0],
            expectedGetValue: 'distinct-abc',
        },
        {
            description: 'Insights preserves short_id',
            groupType: TaxonomicFilterGroupType.Insights,
            value: 'sh0rt',
            item: { name: 'My insight', short_id: 'sh0rt', id: 42 },
            expectedItem: { name: 'My insight', short_id: 'sh0rt', id: 42 },
            getValue: (it: any) => it.short_id,
            expectedGetValue: 'sh0rt',
        },
        {
            description: 'Actions preserves id',
            groupType: TaxonomicFilterGroupType.Actions,
            value: 7,
            item: { name: 'Signup', id: 7, steps: [{ tag_name: 'button' }] },
            expectedItem: { name: 'Signup', id: 7, steps: [{ tag_name: 'button' }] },
            getValue: (it: any) => it.id,
            expectedGetValue: 7,
        },
        {
            description: 'Notebooks preserves short_id and title',
            groupType: TaxonomicFilterGroupType.Notebooks,
            value: 'nb-1',
            item: { title: 'Research', short_id: 'nb-1' },
            expectedItem: { name: 'nb-1', short_id: 'nb-1', title: 'Research' },
            getValue: (it: any) => it.short_id,
            expectedGetValue: 'nb-1',
        },
        {
            description: 'FeatureFlags preserves id, key and active',
            groupType: TaxonomicFilterGroupType.FeatureFlags,
            value: 99,
            item: { id: 99, key: 'new-thing', name: 'New thing', active: false },
            expectedItem: { id: 99, key: 'new-thing', name: 'New thing', active: false },
            getValue: (it: any) => it.id || '',
            expectedGetValue: 99,
        },
        {
            description: 'Groups preserves group_key and the display name',
            groupType: TaxonomicFilterGroupType.GroupsPrefix,
            value: 'org-123',
            item: { group_key: 'org-123', name: 'Acme Inc', group_type_index: 0 },
            expectedItem: { group_key: 'org-123', name: 'Acme Inc', group_type_index: 0 },
            getValue: (it: any) => it.group_key,
            expectedGetValue: 'org-123',
        },
    ])(
        'togglePin minimal item allows source-group getValue to run: $description',
        ({ groupType, value, item, expectedItem, getValue, expectedGetValue }) => {
            logic.actions.togglePin(groupType, 'irrelevant', value, item)
            const storedItem = logic.values.pinnedFilters[0].item
            expect(storedItem).toEqual(expectedItem)
            expect(() => getValue(storedItem)).not.toThrow()
            expect(getValue(storedItem)).toEqual(expectedGetValue)
        }
    )

    it.each([
        {
            description: 'strips Person email and properties',
            item: { name: 'Alice', distinct_ids: ['d1'], email: 'alice@example.com', properties: { plan: 'pro' } },
            expectedItem: { name: 'Alice', distinct_ids: ['d1'] },
        },
        {
            description: 'strips group_properties',
            item: { name: 'Acme', group_key: 'org-1', group_properties: { revenue: 12345 } },
            expectedItem: { name: 'Acme', group_key: 'org-1' },
        },
        {
            description: 'strips a stale _pinnedContext if one happens to be on the source item',
            item: { name: 'x', id: 1, _pinnedContext: { sourceGroupType: 'events', sourceGroupName: 'Events' } },
            expectedItem: { name: 'x', id: 1 },
        },
    ])('togglePin strips PII / heavy fields before persisting: $description', ({ item, expectedItem }) => {
        logic.actions.togglePin(TaxonomicFilterGroupType.Persons, 'Persons', 'pv', item)
        expect(logic.values.pinnedFilters[0].item).toEqual(expectedItem)
    })

    it('togglePin falls back to value for name when item lacks a name', () => {
        logic.actions.togglePin(TaxonomicFilterGroupType.EventProperties, 'Event properties', '$os', {})
        expect(logic.values.pinnedFilters[0].item).toEqual({ name: '$os' })
    })

    it('togglePin removes an existing item when called again with the same groupType and value', () => {
        const item = { name: '$browser' }
        logic.actions.togglePin(TaxonomicFilterGroupType.EventProperties, 'Event properties', '$browser', item)
        expect(logic.values.pinnedFilters).toHaveLength(1)

        logic.actions.togglePin(TaxonomicFilterGroupType.EventProperties, 'Event properties', '$browser', item)
        expect(logic.values.pinnedFilters).toHaveLength(0)
    })

    it('allows the same value in different group types', () => {
        logic.actions.togglePin(TaxonomicFilterGroupType.Events, 'Events', 'name', { name: 'name' })
        logic.actions.togglePin(TaxonomicFilterGroupType.PersonProperties, 'Person properties', 'name', {
            name: 'name',
        })

        expect(logic.values.pinnedFilters).toHaveLength(2)
    })

    it.each([
        { pinned: true, groupType: TaxonomicFilterGroupType.EventProperties, value: '$os', description: 'pinned' },
        {
            pinned: false,
            groupType: TaxonomicFilterGroupType.EventProperties,
            value: '$browser',
            description: 'not pinned',
        },
    ])('isPinned returns $pinned for $description item', ({ pinned, groupType, value }) => {
        logic.actions.togglePin(TaxonomicFilterGroupType.EventProperties, 'Event properties', '$os', { name: '$os' })

        expect(logic.values.isPinned(groupType, value)).toBe(pinned)
    })

    it('pinnedFilterItems includes _pinnedContext with sourceGroupType, sourceGroupName, and value', () => {
        const item = { name: '$pageview' }
        logic.actions.togglePin(TaxonomicFilterGroupType.Events, 'Events', '$pageview', item)

        const items = logic.values.pinnedFilterItems
        expect(items).toHaveLength(1)
        // `value` is on the context so groups whose `getValue` reads a
        // field other than `name` (e.g. Actions → `id`) can roundtrip
        // through the shrunk-down stored item without losing the key
        // needed for isPinned / togglePin lookups.
        expect((items[0] as any)._pinnedContext).toEqual({
            sourceGroupType: TaxonomicFilterGroupType.Events,
            sourceGroupName: 'Events',
            value: '$pageview',
        })
    })

    it('clearPinnedFilters empties the list', () => {
        logic.actions.togglePin(TaxonomicFilterGroupType.Events, 'Events', '$pageview', { name: '$pageview' })
        logic.actions.togglePin(TaxonomicFilterGroupType.PersonProperties, 'Person properties', 'email', {
            name: 'email',
        })
        expect(logic.values.pinnedFilters).toHaveLength(2)

        logic.actions.clearPinnedFilters()
        expect(logic.values.pinnedFilters).toEqual([])
    })

    it.each([
        { groupType: TaxonomicFilterGroupType.HogQLExpression, description: 'HogQLExpression' },
        { groupType: TaxonomicFilterGroupType.SuggestedFilters, description: 'SuggestedFilters' },
        { groupType: TaxonomicFilterGroupType.RecentFilters, description: 'RecentFilters' },
        { groupType: TaxonomicFilterGroupType.PinnedFilters, description: 'PinnedFilters' },
        { groupType: TaxonomicFilterGroupType.Empty, description: 'Empty' },
        { groupType: TaxonomicFilterGroupType.Wildcards, description: 'Wildcards' },
        { groupType: TaxonomicFilterGroupType.MaxAIContext, description: 'MaxAIContext' },
    ])('ignores selections from excluded group type: $description', ({ groupType }) => {
        logic.actions.togglePin(groupType, 'Ignored', 'some-value', { name: 'some-value' })
        expect(logic.values.pinnedFilters).toHaveLength(0)
    })

    it('ignores selections with null value', () => {
        logic.actions.togglePin(TaxonomicFilterGroupType.Events, 'Events', null, { name: 'All events' })
        expect(logic.values.pinnedFilters).toHaveLength(0)
    })

    describe('migration from old quickFilterProperties', () => {
        it('copies old quickFilterProperties from localStorage when pinnedFilters is empty and not yet migrated', () => {
            logic.unmount()
            localStorage.clear()
            localStorage.setItem(OLD_PERSIST_KEY, JSON.stringify(['email', 'name', '$os']))

            initKeaTests()
            logic = taxonomicFilterPinnedPropertiesLogic.build()
            logic.mount()

            const filters = logic.values.pinnedFilters
            expect(filters).toHaveLength(3)
            expect(filters.map((f) => f.value)).toEqual(['email', 'name', '$os'])
            expect(filters.every((f) => f.groupType === TaxonomicFilterGroupType.PersonProperties)).toBe(true)
            expect(filters.every((f) => f.groupName === 'Person properties')).toBe(true)
        })

        it('sets migration flag after migrating', () => {
            logic.unmount()
            localStorage.clear()
            localStorage.setItem(OLD_PERSIST_KEY, JSON.stringify(['email']))

            initKeaTests()
            logic = taxonomicFilterPinnedPropertiesLogic.build()
            logic.mount()

            expect(localStorage.getItem(MIGRATION_KEY)).toBe('1')
        })

        it('does not migrate if already migrated', () => {
            logic.unmount()
            localStorage.clear()
            localStorage.setItem(MIGRATION_KEY, '1')
            localStorage.setItem(OLD_PERSIST_KEY, JSON.stringify(['email', 'name']))

            initKeaTests()
            logic = taxonomicFilterPinnedPropertiesLogic.build()
            logic.mount()

            expect(logic.values.pinnedFilters).toHaveLength(0)
        })

        it('does not migrate if pinnedFilters already has items', () => {
            logic.unmount()
            localStorage.clear()

            initKeaTests()
            logic = taxonomicFilterPinnedPropertiesLogic.build()
            logic.mount()
            logic.actions.togglePin(TaxonomicFilterGroupType.Events, 'Events', '$pageview', { name: '$pageview' })
            logic.unmount()

            localStorage.removeItem(MIGRATION_KEY)
            localStorage.setItem(OLD_PERSIST_KEY, JSON.stringify(['email', 'name']))

            initKeaTests()
            logic = taxonomicFilterPinnedPropertiesLogic.build()
            logic.mount()

            const filters = logic.values.pinnedFilters
            expect(filters).toHaveLength(1)
            expect(filters[0].value).toBe('$pageview')
        })
    })

    describe('hasPinnedContext', () => {
        it.each([
            {
                description: 'an object with a non-null _pinnedContext',
                item: {
                    name: 'foo',
                    _pinnedContext: { sourceGroupType: TaxonomicFilterGroupType.Events, sourceGroupName: 'Events' },
                },
                expected: true,
            },
            {
                description: 'an object without _pinnedContext',
                item: { name: 'foo' },
                expected: false,
            },
            {
                description: 'an object with null _pinnedContext',
                item: { name: 'foo', _pinnedContext: null },
                expected: false,
            },
            {
                description: 'null',
                item: null,
                expected: false,
            },
            {
                description: 'a primitive',
                item: 'string-value',
                expected: false,
            },
        ])('returns $expected for $description', ({ item, expected }) => {
            expect(hasPinnedContext(item)).toBe(expected)
        })
    })

    describe('pickMinimalPinnedItem', () => {
        it.each([
            {
                description: 'strips denylisted fields and keeps everything else',
                input: { name: 'Alice', distinct_ids: ['d1'], email: 'a@example.com', properties: { big: 'blob' } },
                fallback: 'fallback',
                expected: { name: 'Alice', distinct_ids: ['d1'] },
            },
            {
                description: 'uses fallback value when name is missing',
                input: { id: 5 },
                fallback: 'fb',
                expected: { id: 5, name: 'fb' },
            },
            {
                description: 'uses fallback value when name is null (matches the original ?? value semantics)',
                input: { id: 5, name: null },
                fallback: 'fb',
                expected: { id: 5, name: 'fb' },
            },
            {
                description: 'handles non-object input by returning just the fallback name',
                input: null,
                fallback: 'only-name',
                expected: { name: 'only-name' },
            },
            {
                description: 'rejects array input by returning just the fallback name',
                input: ['a', 'b'],
                fallback: 'arr',
                expected: { name: 'arr' },
            },
            {
                description: 'drops undefined-valued fields and functions',
                input: { name: 'x', undef: undefined, fn: () => 1, keep: 'me' },
                fallback: 'x',
                expected: { name: 'x', keep: 'me' },
            },
            {
                description: 'strips a stale _pinnedContext from the source item',
                input: { name: 'x', _pinnedContext: { sourceGroupType: 'events', sourceGroupName: 'Events' } },
                fallback: 'x',
                expected: { name: 'x' },
            },
        ])('$description', ({ input, fallback, expected }) => {
            expect(pickMinimalPinnedItem(input, fallback)).toEqual(expected)
        })
    })

    describe('stripPinnedContext', () => {
        it('removes _pinnedContext and returns remaining fields', () => {
            const item = {
                name: 'email',
                id: 42,
                _pinnedContext: {
                    sourceGroupType: TaxonomicFilterGroupType.PersonProperties,
                    sourceGroupName: 'Person properties',
                },
            }

            const result = stripPinnedContext(item)

            expect(result).toEqual({ name: 'email', id: 42 })
            expect('_pinnedContext' in result).toBe(false)
        })

        it('returns item unchanged when _pinnedContext is absent', () => {
            const item = { name: 'email', id: 42 }
            const result = stripPinnedContext(item)
            expect(result).toEqual({ name: 'email', id: 42 })
        })
    })
})
