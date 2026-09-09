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

export type AccountSidebarProperty = AccountCustomProperty | AccountRelationshipProperty

export interface AccountPropertyOption {
    key: string
    label: string
    kind: AccountSidebarProperty['kind']
}

export function isCustomPropertyEditable(provenance: AccountCustomPropertyProvenance): boolean {
    return provenance === 'manual' || provenance === 'workflow'
}
