import type { PropertyUsageEntryApi } from '~/generated/core/api.schemas'
import { PropertyDefinition, PropertyDefinitionType } from '~/types'

export type PropertyUsageSource = Pick<PropertyDefinition, 'name' | 'type' | 'virtual'> & {
    group_type_index?: number | null
}

/** Maps a property definition to the entry the usage metrics endpoint counts, or null when it tracks no usage. */
export function propertyUsageEntry(definition: PropertyUsageSource): PropertyUsageEntryApi | null {
    // Virtual properties are computed at query time, so no query records them as a stored property.
    if (definition.virtual) {
        return null
    }
    switch (definition.type) {
        case PropertyDefinitionType.Event:
        case PropertyDefinitionType.Person:
        case PropertyDefinitionType.Session:
            return { type: definition.type, name: definition.name }
        case PropertyDefinitionType.Group:
            return definition.group_type_index == null
                ? null
                : { type: definition.type, name: definition.name, group_type_index: definition.group_type_index }
        default:
            return null
    }
}
