import { FilterLogicalOperator } from '~/types'

import { DEFAULT_UNIVERSAL_GROUP_FILTER } from './constants'

describe('UniversalFilters constants', () => {
    test('default group uses the And operator value', () => {
        expect(DEFAULT_UNIVERSAL_GROUP_FILTER.type).toBe(FilterLogicalOperator.And)
    })
})
