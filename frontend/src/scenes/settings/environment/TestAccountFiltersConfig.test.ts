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

    // Every keep-only-matching operator must warn, not just equals/contains. A row like
    // "email ends with @company.com" keeps internal traffic and used to warn about nothing.
    it.each([
        [PropertyOperator.Exact, 'a@b.com'],
        [PropertyOperator.EndsWith, '@company.com'],
        [PropertyOperator.GreaterThan, 5],
        [PropertyOperator.IsDateAfter, '2024-01-01'],
        [PropertyOperator.SemverGt, '1.0.0'],
    ])('warns about a complete positive-operator row (%s)', (operator, value) => {
        const labels = createTestAccountFilterWarningLabels(
            team([{ key: 'email', type: PropertyFilterType.Event, operator, value }]),
            {}
        )
        expect(labels).toHaveLength(1)
    })

    // A value is set so the row is complete; the reason it must not warn is the negative operator.
    it.each([
        [PropertyOperator.IsNot, 'a@b.com'],
        [PropertyOperator.NotEndsWith, '@company.com'],
        [PropertyOperator.NotIn, 5],
        [PropertyOperator.SemverNeq, '1.0.0'],
    ])('ignores a complete negative-operator row (%s)', (operator, value) => {
        const labels = createTestAccountFilterWarningLabels(
            team([{ key: 'email', type: PropertyFilterType.Event, operator, value }]),
            {}
        )
        expect(labels).toEqual([])
    })

    it('ignores a value-free negative operator', () => {
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
