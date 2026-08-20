import { PropertyOperator, PropertyType } from '~/types'

import type { CustomPropertyDisplayTypeEnumApi } from 'products/customer_analytics/frontend/generated/api.schemas'

export function propertyTypeForDisplayType(displayType: CustomPropertyDisplayTypeEnumApi): PropertyType {
    switch (displayType) {
        case 'number':
        case 'currency':
        case 'percent':
            return PropertyType.Numeric
        case 'boolean':
            return PropertyType.Boolean
        case 'date':
        case 'datetime':
            return PropertyType.DateTime
        default:
            return PropertyType.String
    }
}

export const ACCOUNT_CUSTOM_PROPERTY_OPERATOR_ALLOWLIST: PropertyOperator[] = [
    PropertyOperator.Exact,
    PropertyOperator.IsNot,
    PropertyOperator.IContains,
    PropertyOperator.NotIContains,
    PropertyOperator.GreaterThan,
    PropertyOperator.GreaterThanOrEqual,
    PropertyOperator.LessThan,
    PropertyOperator.LessThanOrEqual,
    PropertyOperator.IsSet,
    PropertyOperator.IsNotSet,
    PropertyOperator.IsDateExact,
    PropertyOperator.IsDateBefore,
    PropertyOperator.IsDateAfter,
]
