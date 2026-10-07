import type {
    AccountRelationshipDefinitionApi,
    CustomPropertyDefinitionApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

export const MAX_PINNED_ACCOUNT_PROPERTIES = 50

export type AccountCustomPropertyValue = string | number | boolean | null

export type AccountCustomPropertyProvenance = 'manual' | 'workflow' | 'warehouse' | 'canonical'

export interface AccountRelationshipMember {
    id: number
    email: string
    name?: string
}

export interface AccountCustomProperty {
    key: string
    kind: 'custom'
    definition: CustomPropertyDefinitionApi
    value: AccountCustomPropertyValue
    provenance: AccountCustomPropertyProvenance
    editable?: boolean
}

export interface AccountRelationshipProperty {
    key: string
    kind: 'relationship'
    definition: AccountRelationshipDefinitionApi
    members: AccountRelationshipMember[]
    editable?: boolean
}

export interface PinnableAccountField {
    key: 'stripe_customer_id'
    label: string
}

// Keep in sync with PINNABLE_ACCOUNT_FIELDS in backend/logic/account_property_pins.py.
export const PINNABLE_ACCOUNT_FIELDS: PinnableAccountField[] = [
    { key: 'stripe_customer_id', label: 'Stripe customer ID' },
]

export interface AccountFieldProperty {
    key: string
    kind: 'account_field'
    field: PinnableAccountField
    value: string | null
}

export type AccountSidebarProperty = AccountCustomProperty | AccountRelationshipProperty | AccountFieldProperty

export const ACCOUNT_PROPERTY_KIND_LABELS: Record<AccountSidebarProperty['kind'], string> = {
    custom: 'Custom property',
    relationship: 'Relationship',
    account_field: 'Account field',
}

export interface AccountPropertyOption {
    key: string
    label: string
    kind: AccountSidebarProperty['kind']
}

export function isCustomPropertyEditable(provenance: AccountCustomPropertyProvenance): boolean {
    return provenance === 'manual' || provenance === 'workflow'
}

export function isAccountPropertyEditable(property: AccountSidebarProperty): boolean {
    if (property.kind === 'account_field' || property.editable === false) {
        return false
    }
    return property.kind === 'relationship' || isCustomPropertyEditable(property.provenance)
}

export function accountPropertyLabel(property: AccountSidebarProperty): string {
    return property.kind === 'account_field' ? property.field.label : property.definition.name
}
