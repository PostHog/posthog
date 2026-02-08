import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { QuickFilterContext } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { PropertyOperator, QuickFilter, QuickFilterOption, QuickFilterType } from '~/types'

import { quickFiltersLogic } from './quickFiltersLogic'
import { quickFiltersSectionLogic } from './quickFiltersSectionLogic'

const mockOption1: QuickFilterOption = {
    id: 'opt-1',
    value: 'production',
    label: 'Production',
    operator: PropertyOperator.Exact,
}
const mockOption2: QuickFilterOption = {
    id: 'opt-2',
    value: 'staging',
    label: 'Staging',
    operator: PropertyOperator.Exact,
}
const mockQuickFilters: QuickFilter[] = [
    {
        id: 'filter-1',
        name: 'Environment',
        property_name: '$environment',
        type: 'event' as QuickFilterType,
        options: [mockOption1, mockOption2],
        contexts: [QuickFilterContext.Dashboards],
        created_at: '2024-01-01',
        updated_at: '2024-01-01',
    },
    {
        id: 'filter-2',
        name: 'Browser',
        property_name: '$browser',
        type: 'event' as QuickFilterType,
        options: [{ id: 'opt-chrome', value: 'Chrome', label: 'Chrome', operator: PropertyOperator.Exact }],
        contexts: [QuickFilterContext.Dashboards],
        created_at: '2024-01-01',
        updated_at: '2024-01-01',
    },
]

describe('quickFiltersSectionLogic', () => {
    let logic: ReturnType<typeof quickFiltersSectionLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/quick_filters/': { results: mockQuickFilters },
            },
        })
        initKeaTests()
        logic = quickFiltersSectionLogic({ context: QuickFilterContext.Dashboards })
        logic.mount()
        quickFiltersLogic({ context: QuickFilterContext.Dashboards }).mount()
    })

    describe('selection state', () => {
        it('stores selection keyed by filter ID', () => {
            expectLogic(logic, () => {
                logic.actions.setQuickFilterValue('filter-1', '$environment', mockOption1)
            }).toMatchValues({
                selectedQuickFilters: {
                    'filter-1': {
                        filterId: 'filter-1',
                        propertyName: '$environment',
                        optionId: 'opt-1',
                        value: 'production',
                        operator: PropertyOperator.Exact,
                    },
                },
            })
        })

        it('removes selection by filter ID', () => {
            expectLogic(logic, () => {
                logic.actions.setQuickFilterValue('filter-1', '$environment', mockOption1)
                logic.actions.clearQuickFilter('filter-1')
            }).toMatchValues({
                selectedQuickFilters: {},
            })
        })

        it('multiple filters do not collide', () => {
            const chromeOption = mockQuickFilters[1].options[0]

            expectLogic(logic, () => {
                logic.actions.setQuickFilterValue('filter-1', '$environment', mockOption1)
                logic.actions.setQuickFilterValue('filter-2', '$browser', chromeOption)
            }).toMatchValues({
                selectedQuickFilters: {
                    'filter-1': {
                        filterId: 'filter-1',
                        propertyName: '$environment',
                        optionId: 'opt-1',
                        value: 'production',
                        operator: PropertyOperator.Exact,
                    },
                    'filter-2': {
                        filterId: 'filter-2',
                        propertyName: '$browser',
                        optionId: 'opt-chrome',
                        value: 'Chrome',
                        operator: PropertyOperator.Exact,
                    },
                },
            })
        })
    })

    describe('URL serialization round-trip', () => {
        it.each([
            {
                description: 'empty state produces no URL param',
                selections: {},
                expectedParam: undefined,
            },
            {
                description: 'single filter round-trips correctly',
                selections: {
                    'filter-1': {
                        filterId: 'filter-1',
                        propertyName: '$environment',
                        optionId: 'opt-1',
                        value: 'production',
                        operator: PropertyOperator.Exact,
                    },
                },
                expectedParam: 'filter-1:opt-1',
            },
            {
                description: 'multiple filters round-trip correctly',
                selections: {
                    'filter-1': {
                        filterId: 'filter-1',
                        propertyName: '$environment',
                        optionId: 'opt-1',
                        value: 'production',
                        operator: PropertyOperator.Exact,
                    },
                    'filter-2': {
                        filterId: 'filter-2',
                        propertyName: '$browser',
                        optionId: 'opt-chrome',
                        value: 'Chrome',
                        operator: PropertyOperator.Exact,
                    },
                },
                expectedParam: 'filter-1:opt-1,filter-2:opt-chrome',
            },
            {
                description: 'option IDs containing colons are handled correctly',
                selections: {
                    'filter-1': {
                        filterId: 'filter-1',
                        propertyName: '$prop',
                        optionId: 'opt:with:colons',
                        value: 'value',
                        operator: PropertyOperator.Exact,
                    },
                },
                expectedParam: 'filter-1:opt:with:colons',
            },
        ])('$description', async ({ selections, expectedParam }) => {
            await expectLogic(logic, () => {
                Object.values(selections).forEach((selection) => {
                    logic.actions.setQuickFilterValue(selection.filterId, selection.propertyName, {
                        id: selection.optionId,
                        value: selection.value,
                        label: selection.value as string,
                        operator: selection.operator,
                    })
                })
            }).toMatchValues({
                selectedQuickFilters: selections,
            })

            const searchParams = router.values.currentLocation.searchParams
            if (expectedParam === undefined) {
                expect(searchParams.quick_filters).toBeUndefined()
            } else {
                expect(searchParams.quick_filters).toBe(expectedParam)
            }
        })
    })

    describe('URL to filter restoration', () => {
        const mountWithUrl = async (quickFiltersParam: string): Promise<void> => {
            // Set URL before mounting so params are present when filters load
            router.actions.push('/', { quick_filters: quickFiltersParam })
            logic = quickFiltersSectionLogic({ context: QuickFilterContext.Dashboards })
            logic.mount()
            const filtersLogic = quickFiltersLogic({ context: QuickFilterContext.Dashboards })
            filtersLogic.mount()
            await expectLogic(filtersLogic).toDispatchActions(['loadQuickFiltersSuccess'])
            await expectLogic(logic).toDispatchActions(['restoreFiltersFromUrl'])
        }

        it('restores selection from URL after filters load', async () => {
            await mountWithUrl('filter-1:opt-1')

            expectLogic(logic).toMatchValues({
                selectedQuickFilters: {
                    'filter-1': {
                        filterId: 'filter-1',
                        propertyName: '$environment',
                        optionId: 'opt-1',
                        value: 'production',
                        operator: PropertyOperator.Exact,
                    },
                },
            })
        })

        it('restores multiple filters from URL', async () => {
            await mountWithUrl('filter-1:opt-2,filter-2:opt-chrome')

            expectLogic(logic).toMatchValues({
                selectedQuickFilters: {
                    'filter-1': {
                        filterId: 'filter-1',
                        propertyName: '$environment',
                        optionId: 'opt-2',
                        value: 'staging',
                        operator: PropertyOperator.Exact,
                    },
                    'filter-2': {
                        filterId: 'filter-2',
                        propertyName: '$browser',
                        optionId: 'opt-chrome',
                        value: 'Chrome',
                        operator: PropertyOperator.Exact,
                    },
                },
            })
        })

        it('ignores unknown filter IDs in URL', async () => {
            await mountWithUrl('nonexistent:opt-1')

            expectLogic(logic).toMatchValues({
                selectedQuickFilters: {},
            })
        })

        it('ignores unknown option IDs in URL', async () => {
            await mountWithUrl('filter-1:nonexistent')

            expectLogic(logic).toMatchValues({
                selectedQuickFilters: {},
            })
        })
    })

    describe('deleteFilter clears selection', () => {
        it('clears selection when a connected filter is deleted', async () => {
            await expectLogic(logic, () => {
                logic.actions.setQuickFilterValue('filter-1', '$environment', mockOption1)
                logic.actions.deleteFilter('filter-1')
            })
                .toDispatchActions(['setQuickFilterValue', 'deleteFilter', 'clearQuickFilter'])
                .toMatchValues({
                    selectedQuickFilters: {},
                })
        })
    })

    describe('filterUpdated syncs selection', () => {
        it('updates selection when selected option still exists', async () => {
            const updatedOption: QuickFilterOption = {
                id: 'opt-1',
                value: 'production-updated',
                label: 'Production Updated',
                operator: PropertyOperator.Exact,
            }
            const updatedFilter: QuickFilter = {
                ...mockQuickFilters[0],
                options: [updatedOption, mockOption2],
            }

            await expectLogic(logic, () => {
                logic.actions.setQuickFilterValue('filter-1', '$environment', mockOption1)
                logic.actions.filterUpdated(updatedFilter)
            })
                .toDispatchActions(['setQuickFilterValue', 'filterUpdated', 'setQuickFilterValue'])
                .toMatchValues({
                    selectedQuickFilters: {
                        'filter-1': {
                            filterId: 'filter-1',
                            propertyName: '$environment',
                            optionId: 'opt-1',
                            value: 'production-updated',
                            operator: PropertyOperator.Exact,
                        },
                    },
                })
        })

        it('clears selection when selected option is removed', async () => {
            const updatedFilter: QuickFilter = {
                ...mockQuickFilters[0],
                options: [mockOption2],
            }

            await expectLogic(logic, () => {
                logic.actions.setQuickFilterValue('filter-1', '$environment', mockOption1)
                logic.actions.filterUpdated(updatedFilter)
            })
                .toDispatchActions(['setQuickFilterValue', 'filterUpdated', 'clearQuickFilter'])
                .toMatchValues({
                    selectedQuickFilters: {},
                })
        })
    })
})
