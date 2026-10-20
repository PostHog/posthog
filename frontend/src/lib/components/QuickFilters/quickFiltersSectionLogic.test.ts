import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { QuickFilterContext } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { PropertyOperator, QuickFilter, QuickFilterOption } from '~/types'

import { QuickFiltersEvents } from './consts'
import { autoDiscoveredOption } from './quickFilterOptions'
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
        type: 'manual-options',
        options: [mockOption1, mockOption2],
        contexts: [QuickFilterContext.ErrorTrackingIssueFilters],
        created_at: '2024-01-01',
        updated_at: '2024-01-01',
    },
    {
        id: 'filter-2',
        name: 'Browser',
        property_name: '$browser',
        type: 'manual-options',
        options: [{ id: 'opt-chrome', value: 'Chrome', label: 'Chrome', operator: PropertyOperator.Exact }],
        contexts: [QuickFilterContext.ErrorTrackingIssueFilters],
        created_at: '2024-01-01',
        updated_at: '2024-01-01',
    },
    {
        id: 'filter-3',
        name: 'Region',
        property_name: '$region',
        type: 'manual-options',
        options: [{ id: 'opt:with:colons', value: 'eu-west', label: 'EU West', operator: PropertyOperator.Exact }],
        contexts: [QuickFilterContext.ErrorTrackingIssueFilters],
        created_at: '2024-01-01',
        updated_at: '2024-01-01',
    },
    {
        id: 'filter-4',
        name: 'Release',
        property_name: '$release',
        type: 'auto-discovery',
        options: [],
        contexts: [QuickFilterContext.ErrorTrackingIssueFilters],
        created_at: '2024-01-01',
        updated_at: '2024-01-01',
    },
]

const autoDiscoveredSelection = (value: string): Record<string, unknown> => ({
    filterId: 'filter-4',
    propertyName: '$release',
    optionId: `~${value}`,
    value,
    operator: PropertyOperator.Exact,
})

describe('quickFiltersSectionLogic', () => {
    let logic: ReturnType<typeof quickFiltersSectionLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/quick_filters/': { results: mockQuickFilters },
            },
        })
        initKeaTests()
        logic = quickFiltersSectionLogic({ context: QuickFilterContext.ErrorTrackingIssueFilters })
        logic.mount()
        quickFiltersLogic({ context: QuickFilterContext.ErrorTrackingIssueFilters }).mount()
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

    describe('selection analytics', () => {
        it.each([
            {
                description: 'sends the label and value of a manual option',
                filter: mockQuickFilters[0],
                option: mockOption1,
                expectedValues: { label: 'Production', value: 'production' },
            },
            {
                description: 'leaves out an auto-discovered value, which is raw event data',
                filter: mockQuickFilters[3],
                option: autoDiscoveredOption('v1'),
                expectedValues: {},
            },
        ])('$description', async ({ filter, option, expectedValues }) => {
            await expectLogic(
                quickFiltersLogic({ context: QuickFilterContext.ErrorTrackingIssueFilters })
            ).toDispatchActions(['loadQuickFiltersSuccess'])
            const capture = jest.spyOn(posthog, 'capture').mockReturnValue(undefined)

            logic.actions.setQuickFilterValue(filter.id, filter.property_name, option)

            expect(capture).toHaveBeenCalledWith(QuickFiltersEvents.QuickFilterSelected, {
                name: filter.name,
                property_name: filter.property_name,
                filter_type: filter.type,
                context: QuickFilterContext.ErrorTrackingIssueFilters,
                ...expectedValues,
            })
            capture.mockRestore()
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
                expectedParam: 'filter-1:opt%3Awith%3Acolons',
            },
            {
                description: 'auto-discovered values containing separators are encoded',
                selections: { 'filter-4': autoDiscoveredSelection('v1,2:beta') },
                expectedParam: 'filter-4:~v1%2C2%3Abeta',
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
            logic = quickFiltersSectionLogic({ context: QuickFilterContext.ErrorTrackingIssueFilters })
            logic.mount()
            const filtersLogic = quickFiltersLogic({ context: QuickFilterContext.ErrorTrackingIssueFilters })
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

        it('restores option IDs containing colons from URL', async () => {
            await mountWithUrl('filter-3:opt:with:colons')

            expectLogic(logic).toMatchValues({
                selectedQuickFilters: {
                    'filter-3': {
                        filterId: 'filter-3',
                        propertyName: '$region',
                        optionId: 'opt:with:colons',
                        value: 'eu-west',
                        operator: PropertyOperator.Exact,
                    },
                },
            })
        })

        it('restores auto-discovered values that no option lists', async () => {
            await mountWithUrl(`filter-4:${encodeURIComponent('~v1,2:beta')}`)

            expectLogic(logic).toMatchValues({
                selectedQuickFilters: { 'filter-4': autoDiscoveredSelection('v1,2:beta') },
            })
        })

        it('ignores unknown filter IDs in URL', async () => {
            await mountWithUrl('nonexistent:opt-1')

            expectLogic(logic).toMatchValues({
                selectedQuickFilters: {},
            })
        })

        it.each([
            { description: 'ignores unknown option IDs in URL', param: 'filter-1:nonexistent' },
            {
                description: 'ignores a manual option ID from an old link on an auto-discovery filter',
                param: 'filter-4:opt-1',
            },
        ])('$description', async ({ param }) => {
            await mountWithUrl(param)

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

        it.each([
            {
                description: 'keeps an auto-discovered selection when the filter is renamed',
                selectedFilter: mockQuickFilters[3],
                selectedOption: autoDiscoveredOption('v1'),
                updatedFilter: { ...mockQuickFilters[3], name: 'Version' },
                expectedAction: 'setQuickFilterValue',
                expectedSelection: { 'filter-4': autoDiscoveredSelection('v1') },
            },
            {
                description: 'clears an auto-discovered selection when the property changes',
                selectedFilter: mockQuickFilters[3],
                selectedOption: autoDiscoveredOption('v1'),
                updatedFilter: { ...mockQuickFilters[3], property_name: '$app_version' },
                expectedAction: 'clearQuickFilter',
                expectedSelection: {},
            },
            {
                description: 'clears a manual selection when the filter switches to auto-discovery',
                selectedFilter: mockQuickFilters[0],
                selectedOption: mockOption1,
                updatedFilter: { ...mockQuickFilters[0], type: 'auto-discovery' as const, options: [] },
                expectedAction: 'clearQuickFilter',
                expectedSelection: {},
            },
        ])(
            '$description',
            async ({ selectedFilter, selectedOption, updatedFilter, expectedAction, expectedSelection }) => {
                await expectLogic(logic, () => {
                    logic.actions.setQuickFilterValue(selectedFilter.id, selectedFilter.property_name, selectedOption)
                    logic.actions.filterUpdated(updatedFilter)
                })
                    .toDispatchActions(['setQuickFilterValue', 'filterUpdated', expectedAction])
                    .toMatchValues({ selectedQuickFilters: expectedSelection })
            }
        )

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
