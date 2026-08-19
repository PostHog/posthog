import { PropertyOperator, PropertyType } from '~/types'

import { ACCOUNT_CUSTOM_PROPERTY_OPERATOR_ALLOWLIST, propertyTypeForDisplayType } from './accountsCustomPropertyFilters'

describe('accountsCustomPropertyFilters', () => {
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

    it('does not offer regex operators for Postgres account filters', () => {
        expect(ACCOUNT_CUSTOM_PROPERTY_OPERATOR_ALLOWLIST).not.toContain(PropertyOperator.Regex)
        expect(ACCOUNT_CUSTOM_PROPERTY_OPERATOR_ALLOWLIST).not.toContain(PropertyOperator.NotRegex)
    })
})
