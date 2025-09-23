import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import { v4 as uuidv4 } from 'uuid'

import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { dataTableSavedFiltersLogic } from './dataTableSavedFiltersLogic'

jest.mock('uuid')

const mockQuery: DataTableNode = {
    kind: NodeKind.DataTableNode,
    source: {
        kind: NodeKind.TracesQuery,
        dateRange: {
            date_from: '-7d',
            date_to: null,
        },
        properties: [],
        filterTestAccounts: false,
    },
}

const mockQueryWithFilters: DataTableNode = {
    kind: NodeKind.DataTableNode,
    source: {
        kind: NodeKind.TracesQuery,
        dateRange: {
            date_from: '-30d',
            date_to: null,
        },
        properties: [
            {
                type: PropertyFilterType.Event,
                key: 'test',
                value: 'value',
                operator: PropertyOperator.Exact,
            },
        ],
        filterTestAccounts: true,
    },
}

describe('dataTableSavedFiltersLogic', () => {
    let logic: ReturnType<typeof dataTableSavedFiltersLogic.build>
    let mockSetQuery: jest.Mock
    let mockRouterPush: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        localStorage.clear()
        mockSetQuery = jest.fn()
        ;(uuidv4 as jest.Mock).mockImplementation(() => 'test-uuid')

        mockRouterPush = jest.spyOn(router.actions, 'push').mockImplementation(() => {})
    })

    afterEach(() => {
        logic?.unmount()
        mockRouterPush?.mockRestore()
    })

    describe('with unique key', () => {
        beforeEach(() => {
            logic = dataTableSavedFiltersLogic({
                uniqueKey: 'test-table',
                query: mockQuery,
                setQuery: mockSetQuery,
            })
            logic.mount()
        })

        describe('reducers', () => {
            it('should have correct initial state', () => {
                expectLogic(logic).toMatchValues({
                    savedFilters: [],
                    appliedSavedFilter: null,
                    showSavedFilters: false,
                })
            })

            it('should create a saved filter', () => {
                const filterName = 'My Test Filter'
                logic.actions.createSavedFilter(filterName)

                expectLogic(logic).toMatchValues({
                    savedFilters: [
                        expect.objectContaining({
                            id: 'test-uuid',
                            name: filterName,
                            query: mockQuery,
                        }),
                    ],
                })

                const savedFilter = logic.values.savedFilters[0]
                expect(savedFilter.createdAt).toBeTruthy()
                expect(savedFilter.lastModifiedAt).toBeTruthy()
            })

            it('should update an existing saved filter', () => {
                // Use fake timers to ensure timestamps differ
                jest.useFakeTimers()

                // First create a filter
                logic.actions.createSavedFilter('Original Filter')
                const originalFilter = logic.values.savedFilters[0]

                // Advance time to ensure different timestamp
                jest.advanceTimersByTime(1000)

                // Update it
                logic.actions.updateSavedFilter(originalFilter.id, {
                    name: 'Updated Filter',
                    query: mockQueryWithFilters,
                })

                expectLogic(logic).toMatchValues({
                    savedFilters: [
                        expect.objectContaining({
                            id: originalFilter.id,
                            name: 'Updated Filter',
                            query: mockQueryWithFilters,
                            createdAt: originalFilter.createdAt,
                        }),
                    ],
                })

                const updatedFilter = logic.values.savedFilters[0]
                expect(updatedFilter.lastModifiedAt).not.toBe(originalFilter.lastModifiedAt)

                jest.useRealTimers()
            })

            it('should delete a saved filter', () => {
                // Create two filters
                logic.actions.createSavedFilter('Filter 1')
                ;(uuidv4 as jest.Mock).mockImplementation(() => 'test-uuid-2')
                logic.actions.createSavedFilter('Filter 2')

                expect(logic.values.savedFilters).toHaveLength(2)

                // Delete the first one
                logic.actions.deleteSavedFilter('test-uuid')

                expectLogic(logic).toMatchValues({
                    savedFilters: [
                        expect.objectContaining({
                            id: 'test-uuid-2',
                            name: 'Filter 2',
                        }),
                    ],
                })
            })

            it('should set applied saved filter', () => {
                logic.actions.createSavedFilter('Test Filter')
                const savedFilter = logic.values.savedFilters[0]

                logic.actions.setAppliedSavedFilter(savedFilter)

                expectLogic(logic).toMatchValues({
                    appliedSavedFilter: savedFilter,
                })

                // Can also clear it
                logic.actions.setAppliedSavedFilter(null)

                expectLogic(logic).toMatchValues({
                    appliedSavedFilter: null,
                })
            })

            it('should toggle show saved filters', () => {
                expectLogic(logic).toMatchValues({
                    showSavedFilters: false,
                })

                logic.actions.setShowSavedFilters(true)

                expectLogic(logic).toMatchValues({
                    showSavedFilters: true,
                })

                logic.actions.setShowSavedFilters(false)

                expectLogic(logic).toMatchValues({
                    showSavedFilters: false,
                })
            })
        })

        describe('selectors', () => {
            it('should detect unsaved filter changes', () => {
                // Initially no changes
                expectLogic(logic).toMatchValues({
                    hasUnsavedFilterChanges: false,
                })

                // Create and apply a filter
                logic.actions.createSavedFilter('Test Filter')
                const savedFilter = logic.values.savedFilters[0]
                logic.actions.setAppliedSavedFilter(savedFilter)

                // Still no changes (query matches saved filter)
                expectLogic(logic).toMatchValues({
                    hasUnsavedFilterChanges: false,
                })

                // Change the query - unmount first logic and create new one with different query
                logic.unmount()
                logic = dataTableSavedFiltersLogic({
                    uniqueKey: 'test-table',
                    query: mockQueryWithFilters,
                    setQuery: mockSetQuery,
                })
                logic.mount()

                // Get the saved filter from the new logic instance (loaded from localStorage)
                const reloadedFilter = logic.values.savedFilters[0]
                logic.actions.setAppliedSavedFilter(reloadedFilter)

                // Now there should be unsaved changes
                expectLogic(logic).toMatchValues({
                    hasUnsavedFilterChanges: true,
                })
            })

            it('should not detect changes when no filter is applied', () => {
                // Change the query but don't apply any saved filter
                logic = dataTableSavedFiltersLogic({
                    uniqueKey: 'test-table',
                    query: mockQueryWithFilters,
                    setQuery: mockSetQuery,
                })
                logic.mount()

                expectLogic(logic).toMatchValues({
                    hasUnsavedFilterChanges: false,
                })
            })
        })

        describe('listeners', () => {
            it('should apply a saved filter', () => {
                logic.actions.createSavedFilter('Test Filter')
                const savedFilter = logic.values.savedFilters[0]

                mockRouterPush.mockClear()

                logic.actions.applySavedFilter(savedFilter)

                expect(mockSetQuery).toHaveBeenCalledWith(savedFilter.query)
                expectLogic(logic).toMatchValues({
                    appliedSavedFilter: savedFilter,
                })

                expect(mockRouterPush).toHaveBeenCalledWith(
                    router.values.location.pathname,
                    expect.objectContaining({
                        saved_filter_id: savedFilter.id,
                    })
                )
            })

            it('should set newly created filter as applied and update URL', () => {
                // Reset the mock to clear any previous calls
                mockRouterPush.mockClear()

                logic.actions.createSavedFilter('New Filter')

                const savedFilter = logic.values.savedFilters[0]
                expectLogic(logic).toMatchValues({
                    appliedSavedFilter: savedFilter,
                })

                // Verify no data inconsistency - applied filter should be the exact same object
                const appliedFilter = logic.values.appliedSavedFilter
                expect(appliedFilter).toBe(savedFilter) // Same reference, not a duplicate
                expect(appliedFilter?.id).toBe(savedFilter.id) // Same UUID
                expect(appliedFilter?.createdAt).toBe(savedFilter.createdAt) // Same timestamp

                expect(mockRouterPush).toHaveBeenCalledWith(
                    router.values.location.pathname,
                    expect.objectContaining({
                        saved_filter_id: savedFilter.id,
                    })
                )
            })

            describe('deleteSavedFilter', () => {
                it('should update URL when deleting the currently applied filter', () => {
                    // Create and apply a filter
                    logic.actions.createSavedFilter('Filter to Delete')
                    const filter = logic.values.savedFilters[0]
                    logic.actions.setAppliedSavedFilter(filter)

                    // Clear previous calls from createSavedFilter
                    mockRouterPush.mockClear()

                    logic.actions.deleteSavedFilter(filter.id)

                    // Should remove saved_filter_id from URL
                    expect(mockRouterPush).toHaveBeenCalledWith(router.values.location.pathname, {})
                })

                it('should NOT update URL when deleting a non-applied filter', () => {
                    // Create two filters
                    logic.actions.createSavedFilter('Applied Filter')
                    const appliedFilter = logic.values.savedFilters[0]
                    ;(uuidv4 as jest.Mock).mockImplementation(() => 'other-filter-id')
                    logic.actions.createSavedFilter('Other Filter')
                    const otherFilter = logic.values.savedFilters[1]

                    // Apply the first filter (setAppliedSavedFilter doesn't trigger URL update)
                    logic.actions.setAppliedSavedFilter(appliedFilter)

                    // Clear previous calls from createSavedFilter (called twice)
                    mockRouterPush.mockClear()

                    // Delete the non-applied filter
                    logic.actions.deleteSavedFilter(otherFilter.id)

                    // Should not update URL
                    expect(mockRouterPush).not.toHaveBeenCalled()
                    // Applied filter should remain unchanged
                    expectLogic(logic).toMatchValues({
                        appliedSavedFilter: appliedFilter,
                    })
                })

                it('should handle deleting when no filter is applied', () => {
                    logic.actions.createSavedFilter('Filter 1')
                    const filter = logic.values.savedFilters[0]

                    // Ensure no filter is applied (setAppliedSavedFilter doesn't trigger URL update)
                    logic.actions.setAppliedSavedFilter(null)

                    // Clear previous calls from createSavedFilter
                    mockRouterPush.mockClear()

                    logic.actions.deleteSavedFilter(filter.id)

                    // Should not crash and should not update URL
                    expect(mockRouterPush).not.toHaveBeenCalled()
                })
            })
        })

        describe('localStorage persistence', () => {
            it('should persist saved filters to localStorage', () => {
                logic.actions.createSavedFilter('Persistent Filter')

                // Unmount and remount
                logic.unmount()
                logic = dataTableSavedFiltersLogic({
                    uniqueKey: 'test-table',
                    query: mockQuery,
                    setQuery: mockSetQuery,
                })
                logic.mount()

                expectLogic(logic).toMatchValues({
                    savedFilters: [
                        expect.objectContaining({
                            name: 'Persistent Filter',
                        }),
                    ],
                })
            })

            it('should use separate storage keys for different unique keys', () => {
                // Create filter for first table
                logic.actions.createSavedFilter('Table 1 Filter')

                // Create logic for different table
                const logic2 = dataTableSavedFiltersLogic({
                    uniqueKey: 'different-table',
                    query: mockQuery,
                    setQuery: mockSetQuery,
                })
                logic2.mount()

                // Should have no filters
                expectLogic(logic2).toMatchValues({
                    savedFilters: [],
                })

                // Create filter for second table
                logic2.actions.createSavedFilter('Table 2 Filter')

                // Verify both have their own filters
                expectLogic(logic).toMatchValues({
                    savedFilters: [
                        expect.objectContaining({
                            name: 'Table 1 Filter',
                        }),
                    ],
                })

                expectLogic(logic2).toMatchValues({
                    savedFilters: [
                        expect.objectContaining({
                            name: 'Table 2 Filter',
                        }),
                    ],
                })

                logic2.unmount()
            })
        })
    })

    describe('without unique key', () => {
        it('should not crash but warn about missing unique key', () => {
            const consoleWarnSpy = jest.spyOn(console, 'warn').mockImplementation()

            logic = dataTableSavedFiltersLogic({
                uniqueKey: '',
                query: mockQuery,
                setQuery: mockSetQuery,
            })
            logic.mount()

            // Should work normally even without unique key
            logic.actions.createSavedFilter('Test Filter')
            expectLogic(logic).toMatchValues({
                savedFilters: [
                    expect.objectContaining({
                        name: 'Test Filter',
                    }),
                ],
            })

            consoleWarnSpy.mockRestore()
        })
    })

    describe('edge cases', () => {
        beforeEach(() => {
            logic = dataTableSavedFiltersLogic({
                uniqueKey: 'test-table',
                query: mockQuery,
                setQuery: mockSetQuery,
            })
            logic.mount()
        })

        it('should handle updating non-existent filter gracefully', () => {
            logic.actions.updateSavedFilter('non-existent-id', { name: 'Updated' })

            // Should not crash and filters should remain unchanged
            expectLogic(logic).toMatchValues({
                savedFilters: [],
            })
        })

        it('should handle deleting non-existent filter gracefully', () => {
            logic.actions.createSavedFilter('Existing Filter')

            logic.actions.deleteSavedFilter('non-existent-id')

            // Should not affect existing filters
            expectLogic(logic).toMatchValues({
                savedFilters: [
                    expect.objectContaining({
                        name: 'Existing Filter',
                    }),
                ],
            })
        })

        it('should handle empty filter name', () => {
            logic.actions.createSavedFilter('')

            // Should create filter with empty name
            expectLogic(logic).toMatchValues({
                savedFilters: [
                    expect.objectContaining({
                        name: '',
                    }),
                ],
            })
        })

        it('should handle filters with same name', () => {
            logic.actions.createSavedFilter('Duplicate Name')
            ;(uuidv4 as jest.Mock).mockImplementation(() => 'test-uuid-2')
            logic.actions.createSavedFilter('Duplicate Name')

            // Should allow duplicate names (differentiated by ID)
            expectLogic(logic).toMatchValues({
                savedFilters: [
                    expect.objectContaining({
                        id: 'test-uuid',
                        name: 'Duplicate Name',
                    }),
                    expect.objectContaining({
                        id: 'test-uuid-2',
                        name: 'Duplicate Name',
                    }),
                ],
            })
        })
    })
})
