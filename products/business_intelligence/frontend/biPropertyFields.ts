import { EnterprisePropertyDefinitionApi } from '~/generated/core/api.schemas'
import { BIField } from '~/queries/schema/schema-business-intelligence'
import { escapeRawPropertyAsHogQLIdentifier } from '~/queries/utils'

import {
    getSidebarPropertyDefinitionTarget,
    SidebarPropertyDefinitionTarget,
} from 'products/data_warehouse/frontend/shared/propertyDefinitionTarget'

export function getBIPropertyTarget(field: BIField): SidebarPropertyDefinitionTarget | null {
    if (field.source.connectionId || !['events', 'ai_events', 'persons', 'raw_persons'].includes(field.source.table)) {
        return null
    }
    return getSidebarPropertyDefinitionTarget(field.source.table, field.name, {
        name: field.name,
        hogql_value: field.expression,
        schema_valid: true,
        // Virtual tables serialize child names without their types.
        type: field.type === 'unknown' ? 'json' : field.type,
    })
}

export function buildBIPropertyFields(field: BIField, definitions: EnterprisePropertyDefinitionApi[]): BIField[] {
    return definitions.map((definition) => ({
        id: `${field.id}:${JSON.stringify(definition.name)}`,
        name: `${field.name}.${definition.name}`,
        expression: `${field.expression}.${escapeRawPropertyAsHogQLIdentifier(definition.name)}`,
        source: field.source,
        type:
            definition.property_type === 'Boolean'
                ? 'boolean'
                : definition.property_type === 'DateTime'
                  ? 'datetime'
                  : ['Numeric', 'Duration'].includes(definition.property_type ?? '')
                    ? 'float'
                    : 'string',
    }))
}
