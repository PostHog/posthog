import { expectLogic } from 'kea-test-utils'

import { recentTaxonomicFiltersLogic } from 'lib/components/TaxonomicFilter/recentTaxonomicFiltersLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { filterBarLogic } from './filterBarLogic'
import { filterBarSavedSetsLogic } from './filterBarSavedSetsLogic'

const chrome: AnyPropertyFilter = {
    type: PropertyFilterType.Event,
    key: '$browser',
    operator: PropertyOperator.Exact,
    value: ['Chrome'],
}

describe('filterBarLogic', () => {
    let onChange: jest.Mock
    let logic: ReturnType<typeof filterBarLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/property_definitions/': { results: [], count: 0 },
                '/api/projects/:team_id/sessions/property_definitions/': { results: [], count: 0 },
                '/api/event/values/': { results: [] },
            },
        })
        localStorage.clear()
        initKeaTests()
        onChange = jest.fn()
        recentTaxonomicFiltersLogic.mount()
        recentTaxonomicFiltersLogic.actions.clearRecentFilters()
        logic = filterBarLogic({ pageKey: 'test', filters: [], onChange })
        logic.mount()
    })

    it('keeps a picked field local until it has a value, then reports it once', async () => {
        logic.actions.addField({ categoryId: 'event_properties', key: '$browser', label: 'Browser' }, 'popular')
        expect(logic.values.items).toHaveLength(1)
        expect(logic.values.stage).toBe('values')
        expect(onChange).not.toHaveBeenCalled()

        logic.actions.toggleItemValue(logic.values.items[0].id, 'Chrome', 'list')
        expect(onChange).toHaveBeenLastCalledWith([chrome])

        logic.actions.toggleItemValue(logic.values.items[0].id, 'Chrome', 'list')
        expect(onChange).toHaveBeenLastCalledWith([])
    })

    it('reports a cohort pick at once and leaves the picker on the field list', () => {
        logic.actions.addField({ categoryId: 'cohorts', key: '7', label: 'Power users' }, 'category')
        expect(logic.values.stage).toBe('fields')
        expect(onChange).toHaveBeenCalledWith([
            {
                type: PropertyFilterType.Cohort,
                key: 'id',
                value: 7,
                operator: PropertyOperator.In,
                cohort_name: 'Power users',
            },
        ])
    })

    it('records a recent filter when the picker closes on a complete filter', async () => {
        logic.actions.addField({ categoryId: 'event_properties', key: '$browser', label: 'Browser' }, 'popular')
        logic.actions.setMenuOpen(true)
        logic.actions.toggleItemValue(logic.values.items[0].id, 'Chrome', 'list')
        logic.actions.setMenuOpen(false)
        await expectLogic(recentTaxonomicFiltersLogic).toMatchValues({
            recentFilters: [expect.objectContaining({ value: '$browser', propertyFilter: chrome })],
        })
        expect(logic.values.recentFilterEntries).toEqual([])
        logic.actions.clearItems()
        expect(logic.values.recentFilterEntries).toEqual([chrome])
    })

    it('syncs new props without dropping a chip that still waits for a value', () => {
        logic.actions.addField({ categoryId: 'person_properties', key: 'email', label: 'Email' }, 'search')
        const pendingId = logic.values.items[0].id
        filterBarLogic({ pageKey: 'test', filters: [chrome], onChange }).mount()
        expect(logic.values.items.map((item) => item.filter)).toEqual([
            chrome,
            expect.objectContaining({ key: 'email' }),
        ])
        expect(logic.values.items[1].id).toBe(pendingId)
    })

    it('replaces the bar with a saved set and reports the change', () => {
        filterBarSavedSetsLogic.actions.saveSet('Chrome only', [chrome])
        logic.actions.addField({ categoryId: 'person_properties', key: 'email', label: 'Email' }, 'search')
        logic.actions.applySavedSet(filterBarSavedSetsLogic.values.savedSets[0].id)
        expect(logic.values.items.map((item) => item.filter)).toEqual([chrome])
        expect(onChange).toHaveBeenLastCalledWith([chrome])
    })

    it('does not save an empty name or an empty bar', () => {
        logic.actions.saveCurrentFilters('Nothing here')
        logic.actions.addFilter(chrome, 'recent')
        logic.actions.saveCurrentFilters('   ')
        expect(filterBarSavedSetsLogic.values.savedSets).toEqual([])
    })
})
