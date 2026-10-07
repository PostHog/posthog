import type { AccountsTableAccountField } from '~/queries/schema/schema-general'

import type {
    AccountApi,
    AccountRelationshipApi,
    CustomPropertyValueApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { pinnedPropertyToConfiguratorKey, ResolvedPinnedAccountProperty } from './accountSidebarConfigLogic'
import type { AccountSidebarProperty } from './components/accountPropertyTypes'

export interface AccountSidebarPropertyData {
    customValues: CustomPropertyValueApi[]
    relationships: AccountRelationshipApi[]
    // Loaded only when an account field is pinned.
    account: AccountApi | null
}

// Some account fields are top-level attributes and the others live in `properties`.
function accountFieldValue(account: AccountApi | null, field: AccountsTableAccountField): string | null {
    if (!account) {
        return null
    }
    const values: Record<string, unknown> = { ...account.properties, ...account }
    const value = values[field]
    return typeof value === 'string' && value !== '' ? value : null
}

export function buildAccountSidebarProperties(
    pinnedProperties: ResolvedPinnedAccountProperty[],
    data: AccountSidebarPropertyData | null,
    editable: boolean
): AccountSidebarProperty[] {
    if (!data) {
        return []
    }
    const valuesByDefinition = new Map(data.customValues.map((value) => [value.definition_id, value.value]))
    return pinnedProperties.map((property): AccountSidebarProperty => {
        const key = pinnedPropertyToConfiguratorKey(property.reference)
        if (property.kind === 'account_field') {
            return {
                key,
                kind: 'account_field',
                field: property.field,
                value: accountFieldValue(data.account, property.field.key),
            }
        }
        if (property.kind === 'custom_property') {
            const { definition } = property
            return {
                key,
                kind: 'custom',
                definition,
                value: valuesByDefinition.get(definition.id) ?? null,
                editable,
                provenance: definition.is_canonical
                    ? 'canonical'
                    : definition.source
                      ? 'warehouse'
                      : definition.has_workflow_reference
                        ? 'workflow'
                        : 'manual',
            }
        }
        return {
            key,
            kind: 'relationship',
            definition: property.definition,
            editable,
            members: data.relationships.flatMap((relationship) =>
                relationship.definition.id === property.definition.id && !relationship.ended_at && relationship.user
                    ? [relationship.user]
                    : []
            ),
        }
    })
}
