import { FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

import { buildFilterGroupFromWidgetFilters } from './widgetConfigValidation'

describe('widgetConfigValidation', () => {
    describe('buildFilterGroupFromWidgetFilters', () => {
        it('returns undefined when empty', () => {
            expect(buildFilterGroupFromWidgetFilters(undefined)).toBeUndefined()
            expect(buildFilterGroupFromWidgetFilters({})).toBeUndefined()
        })

        it('builds AND group', () => {
            const filterGroup = buildFilterGroupFromWidgetFilters({
                'qf-1': {
                    filterId: 'qf-1',
                    propertyName: '$browser',
                    optionId: 'opt-1',
                    value: 'Chrome',
                    operator: PropertyOperator.Exact,
                },
            })
            expect(filterGroup).toEqual({
                type: FilterLogicalOperator.And,
                values: [
                    {
                        type: FilterLogicalOperator.And,
                        values: [
                            {
                                type: PropertyFilterType.Event,
                                key: '$browser',
                                operator: PropertyOperator.Exact,
                                value: ['Chrome'],
                            },
                        ],
                    },
                ],
            })
        })
    })
})
