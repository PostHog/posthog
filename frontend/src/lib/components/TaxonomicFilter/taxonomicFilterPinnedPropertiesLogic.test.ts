import { initKeaTests } from '~/test/init'

import {
    hasPinnedContext,
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

    it('togglePin adds an item storing only { name } regardless of what was passed', () => {
        const item = { name: '$browser', id: 'prop-1', description: 'some desc', tags: ['a'] }
        logic.actions.togglePin(TaxonomicFilterGroupType.EventProperties, 'Event properties', '$browser', item)

        const filters = logic.values.pinnedFilters
        expect(filters).toHaveLength(1)
        expect(filters[0]).toEqual(
            expect.objectContaining({
                groupType: TaxonomicFilterGroupType.EventProperties,
                groupName: 'Event properties',
                value: '$browser',
                item: { name: '$browser' },
            })
        )
        expect(typeof filters[0].timestamp).toBe('number')
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

    it('pinnedFilterItems includes _pinnedContext with sourceGroupType and sourceGroupName', () => {
        const item = { name: '$pageview' }
        logic.actions.togglePin(TaxonomicFilterGroupType.Events, 'Events', '$pageview', item)

        const items = logic.values.pinnedFilterItems
        expect(items).toHaveLength(1)
        expect((items[0] as any)._pinnedContext).toEqual({
            sourceGroupType: TaxonomicFilterGroupType.Events,
            sourceGroupName: 'Events',
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
