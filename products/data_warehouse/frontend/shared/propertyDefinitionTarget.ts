import type { PropertyDefinitionsListType } from '~/generated/core/api.schemas'
import type { DatabaseSchemaField } from '~/queries/schema/schema-general'

export type SidebarPropertyDefinitionTarget = {
    type: PropertyDefinitionsListType
    groupTypeIndex?: number
}

export const getSidebarPropertyDefinitionTarget = (
    tableName: string,
    columnPath: string,
    field: DatabaseSchemaField
): SidebarPropertyDefinitionTarget | null => {
    if (field.type !== 'json') {
        return null
    }

    tableName = tableName.replace(/^posthog\./, '')
    const pathSegments = columnPath.split('.')
    const fieldName = pathSegments.at(-1)
    if (fieldName !== 'properties' && fieldName !== 'person_properties') {
        return null
    }

    if (fieldName === 'person_properties') {
        return { type: 'person' }
    }

    const groupPathSegment = pathSegments.find((segment) => /^(?:group|goe)_[0-4]$/.test(segment))
    if (groupPathSegment) {
        return { type: 'group', groupTypeIndex: Number(groupPathSegment.at(-1)) }
    }

    if (
        ['persons', 'raw_persons'].includes(tableName) ||
        pathSegments.some((segment) => ['person', 'pdi', 'poe'].includes(segment))
    ) {
        return { type: 'person' }
    }

    if (['ai_events', 'events'].includes(tableName) && columnPath === 'properties') {
        return { type: 'event' }
    }

    return null
}
