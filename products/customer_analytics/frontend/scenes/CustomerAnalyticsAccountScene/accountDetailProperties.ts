import type {
    AccountApi,
    AccountRelationshipDefinitionApi,
    CustomPropertyDefinitionApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

export const DEFAULT_PINNED_PROPERTY_COUNT = 4

export type AccountPropertyProvenance = 'data_warehouse' | 'workflow' | 'auto' | 'manual'

export const ACCOUNT_FIELD_PROPERTIES = ['website_domain', 'created_at', 'churned_at'] as const
export type AccountFieldProperty = (typeof ACCOUNT_FIELD_PROPERTIES)[number]

const ACCOUNT_FIELD_LABELS: Record<AccountFieldProperty, string> = {
    website_domain: 'Website',
    created_at: 'Created',
    churned_at: 'Churned',
}

export type AccountPropertyDescriptor =
    | {
          key: string
          kind: 'custom'
          label: string
          provenance: AccountPropertyProvenance
          editable: boolean
          definition: CustomPropertyDefinitionApi
      }
    | {
          key: string
          kind: 'relationship'
          label: string
          provenance: 'manual'
          editable: boolean
          relationshipDefinition: AccountRelationshipDefinitionApi
      }
    | {
          key: string
          kind: 'field'
          label: string
          provenance: 'auto'
          editable: false
          field: AccountFieldProperty
      }

export function customPropertyKey(definitionId: string): string {
    return `custom:${definitionId}`
}

export function relationshipPropertyKey(definitionId: string): string {
    return `relationship:${definitionId}`
}

export function fieldPropertyKey(field: AccountFieldProperty): string {
    return `field:${field}`
}

export function customPropertyProvenance(
    definition: Pick<CustomPropertyDefinitionApi, 'has_workflow_reference' | 'is_canonical' | 'source' | 'references'>
): AccountPropertyProvenance {
    if (definition.source) {
        return 'data_warehouse'
    }
    if (definition.has_workflow_reference || definition.references.length > 0) {
        return 'workflow'
    }
    if (definition.is_canonical) {
        return 'auto'
    }
    return 'manual'
}

export function buildAccountPropertyDescriptors(
    definitions: CustomPropertyDefinitionApi[],
    relationshipDefinitions: AccountRelationshipDefinitionApi[]
): AccountPropertyDescriptor[] {
    const custom: AccountPropertyDescriptor[] = definitions
        .filter((definition) => !definition.target_type || definition.target_type === 'account')
        .map((definition) => {
            const provenance = customPropertyProvenance(definition)
            return {
                key: customPropertyKey(definition.id),
                kind: 'custom',
                label: definition.name,
                provenance,
                editable: !definition.is_canonical && !definition.source,
                definition,
            }
        })
    const relationships: AccountPropertyDescriptor[] = relationshipDefinitions.map((relationshipDefinition) => ({
        key: relationshipPropertyKey(relationshipDefinition.id),
        kind: 'relationship',
        label: relationshipDefinition.name,
        provenance: 'manual',
        // Multi-holder relationships are managed on the account's relationships timeline.
        editable: relationshipDefinition.is_single_holder !== false,
        relationshipDefinition,
    }))
    const fields: AccountPropertyDescriptor[] = ACCOUNT_FIELD_PROPERTIES.map((field) => ({
        key: fieldPropertyKey(field),
        kind: 'field',
        label: ACCOUNT_FIELD_LABELS[field],
        provenance: 'auto',
        editable: false,
        field,
    }))
    return [...custom, ...relationships, ...fields]
}

export function defaultPinnedPropertyKeys(descriptors: AccountPropertyDescriptor[]): string[] {
    return descriptors
        .filter((descriptor) => descriptor.kind !== 'field')
        .slice(0, DEFAULT_PINNED_PROPERTY_COUNT)
        .map((descriptor) => descriptor.key)
}

export function resolvePinnedProperties(
    descriptors: AccountPropertyDescriptor[],
    pinnedKeys: string[] | null
): AccountPropertyDescriptor[] {
    const keys = pinnedKeys ?? defaultPinnedPropertyKeys(descriptors)
    const byKey = new Map(descriptors.map((descriptor) => [descriptor.key, descriptor]))
    const pinned: AccountPropertyDescriptor[] = []
    for (const key of keys) {
        const descriptor = byKey.get(key)
        if (descriptor && !pinned.includes(descriptor)) {
            pinned.push(descriptor)
        }
    }
    return pinned
}

export function accountFieldValue(account: AccountApi, field: AccountFieldProperty): string | null {
    if (field === 'website_domain') {
        return account.properties?.website_domain ?? null
    }
    return account[field] ?? null
}
