import { expectLogic } from 'kea-test-utils'

import { recentTaxonomicFiltersLogic } from 'lib/components/TaxonomicFilter/recentTaxonomicFiltersLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

import { filterBarLogic } from './filterBarLogic'
import { filterBarSavedSetsLogic } from './filterBarSavedSetsLogic'

const chrome: AnyPropertyFilter = {
    type: PropertyFilterType.Event,
    key: '$browser',
    operator: PropertyOperator.Exact,
    value: ['Chrome'],
}

const email: AnyPropertyFilter = {
    type: PropertyFilterType.Person,
    key: 'email',
    operator: PropertyOperator.IContains,
    value: 'example.com',
}
const os: AnyPropertyFilter = { ...chrome, key: '$os', value: ['iOS'] } as AnyPropertyFilter
const plan: AnyPropertyFilter = { ...chrome, key: 'plan', value: ['pro'] } as AnyPropertyFilter

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

    it('builds an OR group from a chip and reports it to a surface that stores groups', () => {
        const onFilterGroupChange = jest.fn()
        const grouped = filterBarLogic({
            pageKey: 'grouped',
            filterGroup: { type: FilterLogicalOperator.And, values: [] },
            onFilterGroupChange,
        })
        grouped.mount()
        grouped.actions.addFilter(chrome, 'recent')
        grouped.actions.wrapNodeInGroup(grouped.values.items[0].id, FilterLogicalOperator.Or)
        expect(grouped.values.menuOpen).toBe(true)
        expect(grouped.values.showsStackedEditor).toBe(true)
        grouped.actions.addField({ categoryId: 'event_properties', key: '$browser', label: 'Browser' }, 'popular')
        grouped.actions.toggleItemValue(grouped.values.items[1].id, 'Safari', 'list')
        expect(onFilterGroupChange).toHaveBeenLastCalledWith({
            type: FilterLogicalOperator.And,
            values: [{ type: FilterLogicalOperator.Or, values: [chrome, { ...chrome, value: ['Safari'] }] }],
        })
    })

    it('unwraps a new group when the menu closes without a second row', () => {
        const grouped = filterBarLogic({
            pageKey: 'grouped-unwrap',
            filterGroup: { type: FilterLogicalOperator.And, values: [] },
            onFilterGroupChange: jest.fn(),
        })
        grouped.mount()
        grouped.actions.addFilter(chrome, 'recent')
        grouped.actions.wrapNodeInGroup(grouped.values.items[0].id, FilterLogicalOperator.Or)
        grouped.actions.setMenuOpen(false)
        expect(grouped.values.nodes).toEqual([expect.objectContaining({ filter: chrome })])
    })

    it('flips the whole filter to OR from the top-level rows', () => {
        const onFilterGroupChange = jest.fn()
        const grouped = filterBarLogic({
            pageKey: 'grouped-top-level',
            filterGroup: {
                type: FilterLogicalOperator.And,
                values: [{ type: FilterLogicalOperator.And, values: [chrome, email] }],
            },
            onFilterGroupChange,
        })
        grouped.mount()
        grouped.actions.setTopLevelType(FilterLogicalOperator.Or)
        expect(onFilterGroupChange).toHaveBeenLastCalledWith({
            type: FilterLogicalOperator.And,
            values: [{ type: FilterLogicalOperator.Or, values: [chrome, email] }],
        })
    })

    it('keeps the stacked editor while it is open, and returns to chips when it closes', () => {
        const bar = filterBarLogic({ pageKey: 'stacked', filters: [chrome, email, os, plan], onChange })
        bar.mount()
        expect(bar.values.showsStackedEditor).toBe(true)
        bar.actions.setStackedOpen(true)
        bar.actions.removeItem(bar.values.items[0].id)
        expect(bar.values.showsStackedEditor).toBe(true)
        bar.actions.setStackedOpen(false)
        expect(bar.values.showsStackedEditor).toBe(false)
    })

    it('stops applying a filter while it waits for a value on its new field', () => {
        const bar = filterBarLogic({ pageKey: 'replace', filters: [chrome], onChange })
        bar.mount()
        bar.actions.replaceItemField(bar.values.items[0].id, {
            categoryId: 'person_properties',
            key: 'email',
            label: 'Email',
        })
        expect(onChange).toHaveBeenLastCalledWith([])
        expect(bar.values.items[0].filter).toMatchObject({ type: PropertyFilterType.Person, key: 'email', value: null })
    })

    it('hides a saved group from a bar that stores flat filters', () => {
        filterBarSavedSetsLogic.actions.saveSet('Grouped', [chrome], { type: FilterLogicalOperator.And, values: [] })
        expect(logic.values.availableSavedSets).toEqual([])
    })

    it('does not save an empty name or an empty bar', () => {
        logic.actions.saveCurrentFilters('Nothing here')
        logic.actions.addFilter(chrome, 'recent')
        logic.actions.saveCurrentFilters('   ')
        expect(filterBarSavedSetsLogic.values.savedSets).toEqual([])
    })
})
