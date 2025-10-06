import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { GroupsQuery, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { AppContext, GroupPropertyFilter, PropertyFilterType } from '~/types'

import { groupsListLogic } from './groupsListLogic'

describe('groupsListLogic', () => {
    let logic: ReturnType<typeof groupsListLogic.build>

    beforeEach(() => {
        initKeaTests()
        localStorage.clear()
        window.POSTHOG_APP_CONTEXT = { current_team: { id: 123 } } as AppContext
    })

    afterEach(() => {
        logic?.unmount()
    })

    describe('groupFilters reducer', () => {
        it('should add group-specific properties to URL when filters are set', async () => {
            logic = groupsListLogic({ groupTypeIndex: 0 })
            logic.mount()

            const mockFilters = [
                { key: 'name', value: 'test', operator: 'exact', type: PropertyFilterType.Group },
            ] as GroupPropertyFilter[]

            await expectLogic(logic, () => {
                logic.actions.setGroupFilters(mockFilters as GroupPropertyFilter[])
            }).toMatchValues({
                groupFilters: mockFilters,
            })

            expect(router.values.searchParams).toHaveProperty('properties_0')
            expect(JSON.parse(router.values.searchParams.properties_0)).toEqual(mockFilters)
        })

        it('should restore filters from group-specific URL parameter', async () => {
            const mockFilters = [{ key: 'name', value: 'test', operator: 'exact', type: PropertyFilterType.Group }]

            // Simulate navigating to URL with filters
            router.actions.push('/groups/1', { properties_1: JSON.stringify(mockFilters) })

            logic = groupsListLogic({ groupTypeIndex: 1 })
            logic.mount()

            expect((logic.values.query.source as GroupsQuery).properties).toEqual(mockFilters)
        })

        it('should not apply filters from different group types', async () => {
            const group0Filters = [{ key: 'name', value: 'group0', operator: 'exact', type: PropertyFilterType.Group }]

            // Set URL with group 0 filters
            router.actions.push('/groups/1', { properties_0: JSON.stringify(group0Filters) })

            logic = groupsListLogic({ groupTypeIndex: 1 })
            logic.mount()

            // Group 1 logic should not pick up group 0 filters
            expect((logic.values.query.source as GroupsQuery).properties).toEqual([])
        })

        it('should not clear filters when navigating to clean URL', async () => {
            logic = groupsListLogic({ groupTypeIndex: 0 })
            logic.mount()

            // Set some filters first
            const mockFilters = [{ key: 'name', value: 'test', operator: 'exact', type: PropertyFilterType.Group }]
            logic.actions.setQuery({
                ...logic.values.query,
                source: { ...logic.values.query.source, properties: mockFilters } as GroupsQuery,
            })

            // Navigate to clean URL (no properties parameter)
            router.actions.push('/groups/0', {})

            expect((logic.values.query.source as GroupsQuery).properties).toEqual(mockFilters)
        })

        it('should update groupFilters state when filters are set', async () => {
            logic = groupsListLogic({ groupTypeIndex: 2 })
            logic.mount()

            const mockFilters = [
                { key: 'name', value: 'test', operator: 'exact', type: PropertyFilterType.Group },
            ] as GroupPropertyFilter[]

            await expectLogic(logic, () => {
                logic.actions.setGroupFilters(mockFilters as GroupPropertyFilter[])
            }).toMatchValues({
                groupFilters: mockFilters,
            })

            // Verify filters are set in state
            expect(logic.values.groupFilters).toEqual(mockFilters)
        })

        it('should clear groupFilters when filters are removed', async () => {
            logic = groupsListLogic({ groupTypeIndex: 0 })
            logic.mount()

            const mockFilters = [{ key: 'name', value: 'test', operator: 'exact', type: PropertyFilterType.Group }]
            logic.actions.setQuery({
                ...logic.values.query,
                source: { ...logic.values.query.source, properties: mockFilters } as GroupsQuery,
            })

            expect(logic.values.groupFilters).toEqual(mockFilters)

            logic.actions.setQuery({
                ...logic.values.query,
                source: { ...logic.values.query.source, properties: [] } as GroupsQuery,
            })

            expect(logic.values.groupFilters).toEqual([])
        })

        it('should clear URL parameters when filters are removed', async () => {
            logic = groupsListLogic({ groupTypeIndex: 0 })
            logic.mount()

            // Set filters
            const mockFilters = [{ key: 'name', value: 'test', operator: 'exact', type: PropertyFilterType.Group }]
            logic.actions.setGroupFilters(mockFilters as GroupPropertyFilter[])

            expect(router.values.searchParams.properties_0).toBeTruthy()

            // Clear filters
            logic.actions.setGroupFilters([])

            expect(router.values.searchParams.properties_0).toBeUndefined()
        })

        it('should maintain separate filter state for different group types', async () => {
            // Test with multiple group types simultaneously
            const logic0 = groupsListLogic({ groupTypeIndex: 0 })
            const logic1 = groupsListLogic({ groupTypeIndex: 1 })

            logic0.mount()
            logic1.mount()

            const filters0 = [{ key: 'name', value: 'group0', operator: 'exact', type: PropertyFilterType.Group }]
            const filters1 = [{ key: 'name', value: 'group1', operator: 'exact', type: PropertyFilterType.Group }]

            // Set different filters for each group
            logic0.actions.setQuery({
                ...logic0.values.query,
                source: { ...logic0.values.query.source, properties: filters0 } as GroupsQuery,
            })

            logic1.actions.setQuery({
                ...logic1.values.query,
                source: { ...logic1.values.query.source, properties: filters1 } as GroupsQuery,
            })

            // Verify isolation
            expect((logic0.values.query.source as GroupsQuery).properties).toEqual(filters0)
            expect((logic1.values.query.source as GroupsQuery).properties).toEqual(filters1)
            expect(logic0.values.groupFilters).toEqual(filters0)
            expect(logic1.values.groupFilters).toEqual(filters1)

            logic0.unmount()
            logic1.unmount()
        })

        it('should handle malformed JSON in URL parameters gracefully', async () => {
            router.actions.push('/groups/0', { properties_0: 'invalid-json' })

            logic = groupsListLogic({ groupTypeIndex: 0 })
            logic.mount()

            // Should not crash and should not apply any filters
            expect((logic.values.query.source as GroupsQuery).properties).toEqual([])
        })

        it('should handle missing team ID gracefully', async () => {
            window.POSTHOG_APP_CONTEXT = { current_team: null } as AppContext

            logic = groupsListLogic({ groupTypeIndex: 0 })

            // Should not crash during initialization
            expect(() => logic.mount()).not.toThrow()
        })

        it('should set up default columns while preserving filter persistence', async () => {
            logic = groupsListLogic({ groupTypeIndex: 0 })
            logic.mount()

            // Verify query structure is correct
            expect(logic.values.query.kind).toBe(NodeKind.DataTableNode)
            expect(logic.values.query.source.kind).toBe(NodeKind.GroupsQuery)
            expect((logic.values.query.source as GroupsQuery).group_type_index).toBe(0)
            expect(logic.values.query.propertiesViaUrl).toBe(true)
        })

        it('should trigger setQueryWasModified when query changes', async () => {
            logic = groupsListLogic({ groupTypeIndex: 0 })
            logic.mount()

            const mockFilters = [{ key: 'name', value: 'test', operator: 'exact', type: PropertyFilterType.Group }]

            // Reset the flag first
            logic.actions.setQueryWasModified(false)
            expect(logic.values.queryWasModified).toBe(false)

            // Set query should trigger the flag
            logic.actions.setQuery({
                ...logic.values.query,
                source: { ...logic.values.query.source, properties: mockFilters } as GroupsQuery,
            })

            expect(logic.values.queryWasModified).toBe(true)
        })

        it('should update groupFilters when setGroupFilters is called', async () => {
            logic = groupsListLogic({ groupTypeIndex: 0 })
            logic.mount()

            const mockFilters = [{ key: 'name', value: 'test', operator: 'exact', type: PropertyFilterType.Group }]

            logic.actions.setGroupFilters(mockFilters as GroupPropertyFilter[])

            expect(logic.values.groupFilters).toEqual(mockFilters)
        })
    })

    describe('sorting reducer', () => {
        it('should initialize with empty array', () => {
            logic = groupsListLogic({ groupTypeIndex: 0 })
            logic.mount()

            expect(logic.values.sorting).toEqual([])
        })

        it('should update sorting when setQuery is called with orderBy', async () => {
            logic = groupsListLogic({ groupTypeIndex: 0 })
            logic.mount()

            const mockSorting = ['name', 'age']

            await expectLogic(logic, () => {
                logic.actions.setQuery({
                    ...logic.values.query,
                    source: {
                        ...logic.values.query.source,
                        orderBy: mockSorting,
                    } as GroupsQuery,
                })
            }).toMatchValues({
                sorting: mockSorting,
            })
        })

        it('should reset sorting when setQuery is called with empty orderBy array', async () => {
            logic = groupsListLogic({ groupTypeIndex: 0 })
            logic.mount()

            const initialSorting = ['name', 'age']

            logic.actions.setQuery({
                ...logic.values.query,
                source: {
                    ...logic.values.query.source,
                    orderBy: initialSorting,
                } as GroupsQuery,
            })

            expect(logic.values.sorting).toEqual(initialSorting)

            await expectLogic(logic, () => {
                logic.actions.setQuery({
                    ...logic.values.query,
                    source: {
                        ...logic.values.query.source,
                        orderBy: [],
                    } as GroupsQuery,
                })
            }).toMatchValues({
                sorting: [],
            })
        })

        it('should maintain separate sorting state for different group types', () => {
            const logic1 = groupsListLogic({ groupTypeIndex: 0 })
            const logic2 = groupsListLogic({ groupTypeIndex: 1 })

            logic1.mount()
            logic2.mount()

            const initialSorting1 = ['name', 'age']
            const initialSorting2 = ['email', 'created_at']

            logic1.actions.setQuery({
                ...logic1.values.query,
                source: {
                    ...logic1.values.query.source,
                    orderBy: initialSorting1,
                } as GroupsQuery,
            })

            logic2.actions.setQuery({
                ...logic2.values.query,
                source: {
                    ...logic2.values.query.source,
                    orderBy: initialSorting2,
                } as GroupsQuery,
            })

            expect(logic1.values.sorting).toEqual(initialSorting1)
            expect(logic2.values.sorting).toEqual(initialSorting2)

            logic1.actions.setQuery({
                ...logic1.values.query,
                source: {
                    ...logic1.values.query.source,
                    orderBy: [],
                } as GroupsQuery,
            })

            expect(logic1.values.sorting).toEqual([])
            expect(logic2.values.sorting).toEqual(initialSorting2)

            logic1.unmount()
            logic2.unmount()
        })
    })

    describe('URL parameter restoration', () => {
        const baseSelect = ['group_name', 'key', 'created_at']

        it('should restore properties, columns, and sorting from URL parameters', async () => {
            const mockProperties = [{ key: 'name', value: 'test', operator: 'exact', type: PropertyFilterType.Group }]
            const mockSelect = ['mrr', 'arr']
            const mockOrderBy = ['mrr DESC']

            router.actions.push('/groups/0', {
                properties_0: JSON.stringify(mockProperties),
                select_0: JSON.stringify(mockSelect),
                orderBy_0: JSON.stringify(mockOrderBy),
            })

            logic = groupsListLogic({ groupTypeIndex: 0 })
            logic.mount()

            const source = logic.values.query.source as GroupsQuery
            expect(source.properties).toEqual(mockProperties)
            expect(source.select).toEqual(mockSelect)
            expect(source.orderBy).toEqual(mockOrderBy)
        })

        it('should only restore parameters for the matching group type', async () => {
            const group0Properties = [
                { key: 'name', value: 'group0', operator: 'exact', type: PropertyFilterType.Group },
            ]
            const group1Properties = [
                { key: 'name', value: 'group1', operator: 'exact', type: PropertyFilterType.Group },
            ]

            router.actions.push('/groups/0', {
                properties_0: JSON.stringify(group0Properties),
                properties_1: JSON.stringify(group1Properties),
                select_0: JSON.stringify(['col0']),
                select_1: JSON.stringify(['col1']),
            })

            logic = groupsListLogic({ groupTypeIndex: 0 })
            logic.mount()

            const source = logic.values.query.source as GroupsQuery
            expect(source.properties).toEqual(group0Properties)
            expect(source.select).toEqual(['col0'])
        })

        it('should handle partial URL parameters gracefully', async () => {
            const mockProperties = [{ key: 'name', value: 'test', operator: 'exact', type: PropertyFilterType.Group }]

            router.actions.push('/groups/0', {
                properties_0: JSON.stringify(mockProperties),
                // select_0 missing
                orderBy_0: JSON.stringify(['name']),
            })

            logic = groupsListLogic({ groupTypeIndex: 0 })
            logic.mount()

            const source = logic.values.query.source as GroupsQuery
            expect(source.properties).toEqual(mockProperties)
            expect(source.select).toEqual(baseSelect)
            expect(source.orderBy).toEqual(['name'])
        })

        it('should handle empty/falsy URL parameters falling back to defaults', async () => {
            router.actions.push('/groups/0', {
                properties_0: JSON.stringify([]),
                select_0: '',
                orderBy_0: JSON.stringify(null),
            })

            logic = groupsListLogic({ groupTypeIndex: 0 })
            logic.mount()

            const source = logic.values.query.source as GroupsQuery
            expect(source.properties).toEqual([])
            expect(source.select).toEqual(baseSelect)
            expect(source.orderBy).toEqual([])
        })

        it('should handle malformed JSON in URL parameters falling back to defaults', async () => {
            router.actions.push('/groups/0', {
                properties_0: 'invalid-json',
                select_0: '{"incomplete": json',
                orderBy_0: 'not-json-at-all',
            })

            logic = groupsListLogic({ groupTypeIndex: 0 })

            expect(() => logic.mount()).not.toThrow()

            const source = logic.values.query.source as GroupsQuery
            expect(source.properties).toEqual([])
            expect(source.select).toEqual(baseSelect)
            expect(source.orderBy).toEqual([])
        })

        it('should not override query when URL parameters are missing', async () => {
            router.actions.push('/groups/0', {})

            logic = groupsListLogic({ groupTypeIndex: 0 })
            logic.mount()

            const source = logic.values.query.source as GroupsQuery
            expect(source.properties).toEqual([])
        })
    })
})
