import { Properties } from '~/plugin-scaffold'

import { GroupTypeToColumnIndex, ProjectId, TeamId } from '../../types'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'

export function enrichPropertiesWithGroupTypes(properties: Properties, groupTypes: GroupTypeToColumnIndex): Properties {
    const groups = properties.$groups
    if (typeof groups !== 'object' || groups === null || Array.isArray(groups)) {
        return properties
    }
    for (const [groupType, groupIdentifier] of Object.entries(groups)) {
        if (groupType in groupTypes) {
            // :TODO: Update event column instead
            properties[`$group_${groupTypes[groupType]}`] = groupIdentifier
        }
    }
    return properties
}

export async function addGroupProperties(
    teamId: TeamId,
    projectId: ProjectId,
    properties: Properties,
    groupTypeManager: GroupTypeManager
): Promise<Properties> {
    const groups = properties.$groups
    if (typeof groups !== 'object' || groups === null || Array.isArray(groups)) {
        return properties
    }
    const resolvedTypes: GroupTypeToColumnIndex = {}
    for (const [groupType] of Object.entries(groups)) {
        const columnIndex = await groupTypeManager.fetchGroupTypeIndex(teamId, projectId, groupType)
        if (columnIndex !== null) {
            resolvedTypes[groupType] = columnIndex
        }
    }
    return enrichPropertiesWithGroupTypes(properties, resolvedTypes)
}
