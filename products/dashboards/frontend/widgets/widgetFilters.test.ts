import { PropertyOperator } from '~/types'

import { buildFilterGroupFromWidgetFilters } from './widgetFilters'

describe('widgetFilters', () => {
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
