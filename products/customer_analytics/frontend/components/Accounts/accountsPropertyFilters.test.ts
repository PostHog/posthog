import { AccountsTableAccountField } from '~/queries/schema/schema-general'
import { PropertyOperator, PropertyType } from '~/types'

import {
    ACCOUNT_FIELD_PROPERTY_TYPES,
    ACCOUNT_FIELD_TAXONOMIC_OPTIONS,
    ACCOUNT_FILTER_OPERATOR_ALLOWLIST,
    accountFilterStaticValueOptions,
    propertyTypeForDisplayType,
} from './accountsPropertyFilters'

describe('accountsPropertyFilters', () => {
    it.each([
        ['number', PropertyType.Numeric],
        ['currency', PropertyType.Numeric],
        ['percent', PropertyType.Numeric],
        ['boolean', PropertyType.Boolean],
        ['date', PropertyType.DateTime],
        ['datetime', PropertyType.DateTime],
        ['text', PropertyType.String],
    ] as const)('maps %s definitions to %s filters', (displayType, propertyType) => {
        expect(propertyTypeForDisplayType(displayType)).toBe(propertyType)
    })

    it('defines every native account field with its filter type', () => {
        expect(ACCOUNT_FIELD_TAXONOMIC_OPTIONS.map(({ id }) => id)).toEqual(Object.values(AccountsTableAccountField))
        expect(ACCOUNT_FIELD_PROPERTY_TYPES[AccountsTableAccountField.IgnoredAt]).toBe(PropertyType.DateTime)
        expect(ACCOUNT_FIELD_PROPERTY_TYPES[AccountsTableAccountField.ExternalId]).toBe(PropertyType.String)
    })

    it('does not offer regex operators for Postgres account filters', () => {
        expect(ACCOUNT_FILTER_OPERATOR_ALLOWLIST).not.toContain(PropertyOperator.Regex)
        expect(ACCOUNT_FILTER_OPERATOR_ALLOWLIST).not.toContain(PropertyOperator.NotRegex)
    })

    it('suppresses value fetches for native fields but lets custom properties fetch', () => {
        for (const { id } of ACCOUNT_FIELD_TAXONOMIC_OPTIONS) {
            expect(accountFilterStaticValueOptions(id)).toEqual([])
        }
        // Custom property keys are definition ids, which must keep fetching from their endpoint
        expect(accountFilterStaticValueOptions('123')).toBeNull()
    })
})
