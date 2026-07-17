import { FilterLogicalOperator } from '~/types'

import { DEFAULT_UNIVERSAL_GROUP_FILTER } from './constants'

describe('UniversalFilters constants', () => {
    // Guards the unchecked `'AND' as FilterLogicalOperator` cast in constants.ts against drifting from the real enum value.
    test('default group uses the And operator value', () => {
        expect(DEFAULT_UNIVERSAL_GROUP_FILTER.type).toBe(FilterLogicalOperator.And)
    })
})
