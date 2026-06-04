import { PropertyOperator } from '~/types'
import type { QuickFilter } from '~/types'

import {
    buildFilterGroupFromWidgetFilters,
    getAllowedWidgetFilterIds,
    restoreWidgetFiltersFromConfig,
    widgetFiltersForSave,
} from './widgetFilters'

describe('widgetFilters', () => {
    const mockFilter = (id: string, name: string): QuickFilter => ({
        id,
        name,
        property_name: '$browser',
        context: 'dashboards',
        options: [],
        created_at: '',
        updated_at: '',
    })

    it('getAllowedWidgetFilterIds filters with predicate', () => {
        const filters = [mockFilter('a', 'Environment'), mockFilter('b', 'Other')]
        expect(getAllowedWidgetFilterIds(filters, (f) => f.name === 'Environment')).toEqual(['a'])
    })

    it('widgetFiltersForSave maps selected tile filters', () => {
        expect(
            widgetFiltersForSave({
                'qf-1': {
                    filterId: 'qf-1',
                    propertyName: '$browser',
                    optionId: 'opt-1',
                    value: 'Chrome',
                    operator: PropertyOperator.Exact,
                },
            })
        ).toEqual({
            'qf-1': {
                filterId: 'qf-1',
                propertyName: '$browser',
                optionId: 'opt-1',
                value: 'Chrome',
                operator: PropertyOperator.Exact,
            },
        })
    })

    it('restoreWidgetFiltersFromConfig clears then restores', () => {
        const restoreQuickFilterValue = jest.fn()
        const restoreClearQuickFilter = jest.fn()
        restoreWidgetFiltersFromConfig(
            {
                'qf-1': {
                    filterId: 'qf-1',
                    propertyName: '$browser',
                    optionId: 'opt-1',
                    value: 'Chrome',
                    operator: PropertyOperator.Exact,
                },
            },
            restoreQuickFilterValue,
            restoreClearQuickFilter,
            ['qf-1']
        )
        expect(restoreClearQuickFilter).toHaveBeenCalledWith('qf-1')
        expect(restoreQuickFilterValue).toHaveBeenCalled()
    })

    it('buildFilterGroupFromWidgetFilters returns undefined when empty', () => {
        expect(buildFilterGroupFromWidgetFilters(undefined)).toBeUndefined()
        expect(buildFilterGroupFromWidgetFilters({})).toBeUndefined()
    })

    it('buildFilterGroupFromWidgetFilters builds AND group', () => {
        const filterGroup = buildFilterGroupFromWidgetFilters({
            'qf-1': {
                filterId: 'qf-1',
                propertyName: '$browser',
                optionId: 'opt-1',
                value: 'Chrome',
                operator: PropertyOperator.Exact,
            },
        })
        expect(filterGroup?.values[0].values).toHaveLength(1)
    })
})
