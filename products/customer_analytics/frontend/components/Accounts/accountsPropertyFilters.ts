import type { PropValue } from '~/models/propertyDefinitionsModel'
import { AccountsTableAccountField } from '~/queries/schema/schema-general'
import {
    AccountCustomPropertyFilter,
    PropertyDefinitionType,
    PropertyFilterType,
    PropertyOperator,
    PropertyType,
} from '~/types'

import type { CustomPropertyDisplayTypeEnumApi } from 'products/customer_analytics/frontend/generated/api.schemas'

export type AccountPropertyFilter = Omit<AccountCustomPropertyFilter, 'type'> & {
    type: PropertyFilterType.Account
}

export type AccountFilter = AccountPropertyFilter | AccountCustomPropertyFilter

export interface AccountFieldTaxonomicOption {
    id: AccountsTableAccountField
    name: string
    property_type: PropertyType
    type: PropertyDefinitionType.Account
}

export const ACCOUNT_FIELD_TAXONOMIC_OPTIONS: AccountFieldTaxonomicOption[] = [
    {
        id: AccountsTableAccountField.Name,
        name: 'Name',
        property_type: PropertyType.String,
        type: PropertyDefinitionType.Account,
    },
    {
        id: AccountsTableAccountField.ExternalId,
        name: 'External ID',
        property_type: PropertyType.String,
        type: PropertyDefinitionType.Account,
    },
    {
        id: AccountsTableAccountField.CreatedAt,
        name: 'Created at',
        property_type: PropertyType.DateTime,
        type: PropertyDefinitionType.Account,
    },
    {
        id: AccountsTableAccountField.UpdatedAt,
        name: 'Updated at',
        property_type: PropertyType.DateTime,
        type: PropertyDefinitionType.Account,
    },
    {
        id: AccountsTableAccountField.ChurnedAt,
        name: 'Churned at',
        property_type: PropertyType.DateTime,
        type: PropertyDefinitionType.Account,
    },
    {
        id: AccountsTableAccountField.IgnoredAt,
        name: 'Ignored at',
        property_type: PropertyType.DateTime,
        type: PropertyDefinitionType.Account,
    },
    {
        id: AccountsTableAccountField.StripeCustomerId,
        name: 'Stripe customer ID',
        property_type: PropertyType.String,
        type: PropertyDefinitionType.Account,
    },
    {
        id: AccountsTableAccountField.HubspotDealId,
        name: 'HubSpot deal ID',
        property_type: PropertyType.String,
        type: PropertyDefinitionType.Account,
    },
    {
        id: AccountsTableAccountField.BillingId,
        name: 'Billing ID',
        property_type: PropertyType.String,
        type: PropertyDefinitionType.Account,
    },
    {
        id: AccountsTableAccountField.SalesforceId,
        name: 'Salesforce ID',
        property_type: PropertyType.String,
        type: PropertyDefinitionType.Account,
    },
    {
        id: AccountsTableAccountField.ZendeskId,
        name: 'Zendesk ID',
        property_type: PropertyType.String,
        type: PropertyDefinitionType.Account,
    },
]

export const ACCOUNT_FIELD_PROPERTY_TYPES = Object.fromEntries(
    ACCOUNT_FIELD_TAXONOMIC_OPTIONS.map(({ id, property_type }) => [id, property_type])
) as Record<AccountsTableAccountField, PropertyType>

export function isAccountPropertyFilter(filter: AccountFilter): filter is AccountPropertyFilter {
    return filter.type === PropertyFilterType.Account
}

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

export const ACCOUNT_FILTER_OPERATOR_ALLOWLIST: PropertyOperator[] = [
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

export const ACCOUNT_CUSTOM_PROPERTY_OPERATOR_ALLOWLIST = ACCOUNT_FILTER_OPERATOR_ALLOWLIST

const NATIVE_ACCOUNT_FIELD_KEYS = new Set<string>(ACCOUNT_FIELD_TAXONOMIC_OPTIONS.map(({ id }) => id))

// Native account fields have no property-values endpoint, so an empty static list
// suppresses the value fetch that would otherwise 404 and toast. Custom properties
// return null so they still fetch suggestions from their own endpoint.
export function accountFilterStaticValueOptions(propertyKey: string): PropValue[] | null {
    return NATIVE_ACCOUNT_FIELD_KEYS.has(propertyKey) ? [] : null
}
