import type {
    AccountRelationshipApi,
    CustomPropertyValueApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { pinnedPropertyToConfiguratorKey, ResolvedPinnedAccountProperty } from './accountSidebarConfigLogic'
import type { AccountSidebarProperty } from './components/accountPropertyTypes'

export interface AccountSidebarPropertyData {
    customValues: CustomPropertyValueApi[]
    relationships: AccountRelationshipApi[]
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
