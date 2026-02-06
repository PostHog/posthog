import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { QuickFilterContext } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { PropertyOperator, QuickFilter } from '~/types'

import { quickFiltersLogic } from './quickFiltersLogic'
import { ModalView, quickFiltersModalLogic } from './quickFiltersModalLogic'

const mockQuickFilters: QuickFilter[] = [
    {
        id: 'filter-1',
        name: 'Environment',
        property_name: '$environment',
        type: 'manual-options',
        options: [{ id: 'opt-1', value: 'prod', label: 'Production', operator: PropertyOperator.Exact }],
        contexts: [QuickFilterContext.Dashboards],
        created_at: '2024-01-01',
        updated_at: '2024-01-01',
    },
    {
        id: 'filter-2',
        name: 'Browser',
        property_name: '$browser',
        type: 'manual-options',
        options: [{ id: 'opt-chrome', value: 'Chrome', label: 'Chrome', operator: PropertyOperator.Exact }],
        contexts: [QuickFilterContext.Dashboards],
        created_at: '2024-01-01',
        updated_at: '2024-01-01',
    },
    {
        id: 'filter-3',
        name: 'Country',
        property_name: '$geoip_country_code',
        type: 'manual-options',
        options: [{ id: 'opt-us', value: 'US', label: 'United States', operator: PropertyOperator.Exact }],
        contexts: [QuickFilterContext.Dashboards],
        created_at: '2024-01-01',
        updated_at: '2024-01-01',
    },
]

describe('quickFiltersModalLogic', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/quick_filters/': { results: mockQuickFilters },
            },
            delete: {
                '/api/environments/:team_id/quick_filters/:id/': [204],
            },
        })
        initKeaTests()
    })

    describe('filteredQuickFilters', () => {
        const mountWithLoadedFilters = async (): Promise<ReturnType<typeof quickFiltersModalLogic>> => {
            const logic = quickFiltersModalLogic({
                context: QuickFilterContext.Dashboards,
            })
            logic.mount()

            // Wait for the connected quickFiltersLogic to finish loading
            await expectLogic(quickFiltersLogic({ context: QuickFilterContext.Dashboards }))
                .toDispatchActions(['loadQuickFiltersSuccess'])
                .toMatchValues({ quickFilters: mockQuickFilters })

            return logic
        }

        it('returns all filters when query is empty', async () => {
            const logic = await mountWithLoadedFilters()

            await expectLogic(logic, () => {
                logic.actions.openModal()
            }).toMatchValues({
                filteredQuickFilters: mockQuickFilters,
            })
        })

        it('returns all filters when query is whitespace', async () => {
            const logic = await mountWithLoadedFilters()

            await expectLogic(logic, () => {
                logic.actions.openModal()
                logic.actions.setSearchQuery('   ')
            }).toMatchValues({
                filteredQuickFilters: mockQuickFilters,
            })
        })

        it.each([
            ['name', 'environment', ['filter-1']],
            ['name', 'Browser', ['filter-2']],
            ['name', 'count', ['filter-3']],
        ])('filters by %s: %s', async (_, query, expectedIds) => {
            const logic = await mountWithLoadedFilters()

            await expectLogic(logic, () => {
                logic.actions.openModal()
                logic.actions.setSearchQuery(query)
            }).toMatchValues({
                filteredQuickFilters: mockQuickFilters.filter((f) => expectedIds.includes(f.id)),
            })
        })

        it.each([
            ['property_name', '$environment', ['filter-1']],
            ['property_name', 'browser', ['filter-2']],
            ['property_name', 'geoip', ['filter-3']],
        ])('filters by %s: %s', async (_, query, expectedIds) => {
            const logic = await mountWithLoadedFilters()

            await expectLogic(logic, () => {
                logic.actions.openModal()
                logic.actions.setSearchQuery(query)
            }).toMatchValues({
                filteredQuickFilters: mockQuickFilters.filter((f) => expectedIds.includes(f.id)),
            })
        })

        it.each([
            ['option label', 'production', ['filter-1']],
            ['option label', 'chrome', ['filter-2']],
            ['option label', 'united', ['filter-3']],
        ])('filters by %s: %s', async (_, query, expectedIds) => {
            const logic = await mountWithLoadedFilters()

            await expectLogic(logic, () => {
                logic.actions.openModal()
                logic.actions.setSearchQuery(query)
            }).toMatchValues({
                filteredQuickFilters: mockQuickFilters.filter((f) => expectedIds.includes(f.id)),
            })
        })

        it('returns empty array when no matches', async () => {
            const logic = await mountWithLoadedFilters()

            await expectLogic(logic, () => {
                logic.actions.openModal()
                logic.actions.setSearchQuery('nonexistent')
            }).toMatchValues({
                filteredQuickFilters: [],
            })
        })

        it('is case insensitive', async () => {
            const logic = await mountWithLoadedFilters()

            await expectLogic(logic, () => {
                logic.actions.openModal()
                logic.actions.setSearchQuery('ENVIRONMENT')
            }).toMatchValues({
                filteredQuickFilters: [mockQuickFilters[0]],
            })
        })
    })

    describe('onNewFilterCreated callback', () => {
        it('invokes callback when a new filter appears while modal is open and view returns to list', async () => {
            const onNewFilterCreated = jest.fn()

            const logic = quickFiltersModalLogic({
                context: QuickFilterContext.Dashboards,
                onNewFilterCreated,
            })
            const filtersLogic = quickFiltersLogic({ context: QuickFilterContext.Dashboards })

            logic.mount()
            filtersLogic.mount()

            // Initial load
            await expectLogic(filtersLogic)
                .toDispatchActions(['loadQuickFiltersSuccess'])
                .toMatchValues({ quickFilters: mockQuickFilters })

            // Opening modal records filter IDs in cache
            await expectLogic(logic, () => {
                logic.actions.openModal()
            }).toFinishAllListeners()

            // Simulate a new filter being created (appears in quickFilters)
            const newFilter: QuickFilter = {
                id: 'filter-new',
                name: 'New Filter',
                property_name: '$new_prop',
                type: 'manual-options',
                options: [{ id: 'opt-new', value: 'val', label: 'Val', operator: PropertyOperator.Exact }],
                contexts: [QuickFilterContext.Dashboards],
                created_at: '2024-01-02',
                updated_at: '2024-01-02',
            }
            filtersLogic.actions.loadQuickFiltersSuccess([...mockQuickFilters, newFilter])

            // Returning to list view should trigger the callback with the new filter
            await expectLogic(logic, () => {
                logic.actions.setView(ModalView.List)
            }).toFinishAllListeners()

            expect(onNewFilterCreated).toHaveBeenCalledTimes(1)
            expect(onNewFilterCreated).toHaveBeenCalledWith(expect.objectContaining({ id: 'filter-new' }))
        })
    })
})
