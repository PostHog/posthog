import {
    type EnterprisePropertyDefinitionApi,
    type PropertyUsageEntryApi,
    PropertyDefinitionTypeNameEnumApi,
} from '~/generated/core/api.schemas'
import { PropertyDefinitionType } from '~/types'

export interface PropertyUsageSource {
    name: EnterprisePropertyDefinitionApi['name']
    // Definitions built on the frontend, such as virtual ones, carry the wider PropertyDefinitionType.
    type?: EnterprisePropertyDefinitionApi['type'] | PropertyDefinitionType
    group_type_index?: EnterprisePropertyDefinitionApi['group_type_index']
    virtual?: boolean
}

/** Maps a property definition to the entry the usage metrics endpoint counts, or null when it tracks no usage. */
export function propertyUsageEntry(definition: PropertyUsageSource): PropertyUsageEntryApi | null {
    // Virtual properties are computed at query time, so no query records them as a stored property.
    if (definition.virtual) {
        return null
    }
    switch (definition.type) {
        case PropertyDefinitionTypeNameEnumApi.Event:
        case PropertyDefinitionTypeNameEnumApi.Person:
        case PropertyDefinitionTypeNameEnumApi.Session:
            return { type: definition.type, name: definition.name }
        case PropertyDefinitionTypeNameEnumApi.Group:
            return definition.group_type_index == null
                ? null
                : { type: definition.type, name: definition.name, group_type_index: definition.group_type_index }
        default:
            return null
    }
}
