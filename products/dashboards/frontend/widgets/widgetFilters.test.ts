import { PropertyOperator } from '~/types'
import type { QuickFilter } from '~/types'

import { buildFilterGroupFromWidgetFilters, getAllowedWidgetFilterDefinitions } from './widgetFilters'

describe('widgetFilters', () => {
    const mockFilter = (id: string, name: string, propertyName = '$browser'): QuickFilter => ({
        id,
        name,
        property_name: propertyName,
        context: 'dashboards',
        options: [],
        created_at: '',
        updated_at: '',
    })

    it('getAllowedWidgetFilterDefinitions filters with predicate', () => {
        const filters = [mockFilter('a', 'Environment', '$environment'), mockFilter('b', 'Other', '$other')]
        expect(
            getAllowedWidgetFilterDefinitions(filters, (f) => f.property_name === '$environment').map((f) => f.id)
        ).toEqual(['a'])
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
