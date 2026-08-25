import { PropertyFilterType, PropertyOperator, type TeamPublicType } from '~/types'

import { createTestAccountFilterWarningLabels } from './TestAccountFiltersConfig'

describe('createTestAccountFilterWarningLabels', () => {
    function team(filters: any[]): TeamPublicType {
        return { test_account_filters: filters } as TeamPublicType
    }

    it('ignores a positive-operator row that has no value yet', () => {
        // A row still on the default operator with no value is mid-edit, so it must not warn.
        const labels = createTestAccountFilterWarningLabels(
            team([{ key: 'email', type: PropertyFilterType.Event, operator: PropertyOperator.Exact }]),
            {}
        )
        expect(labels).toEqual([])
    })

    it('warns about a complete positive-operator row', () => {
        const labels = createTestAccountFilterWarningLabels(
            team([
                { key: 'email', type: PropertyFilterType.Event, operator: PropertyOperator.Exact, value: 'a@b.com' },
            ]),
            {}
        )
        expect(labels).toHaveLength(1)
    })

    it('ignores a negative-operator row', () => {
        const labels = createTestAccountFilterWarningLabels(
            team([{ key: 'email', type: PropertyFilterType.Event, operator: PropertyOperator.IsNotSet }]),
            {}
        )
        expect(labels).toEqual([])
    })

    it('warns about a positive operator that needs no value', () => {
        const labels = createTestAccountFilterWarningLabels(
            team([{ key: 'email', type: PropertyFilterType.Event, operator: PropertyOperator.IsSet }]),
            {}
        )
        expect(labels).toHaveLength(1)
    })
})
