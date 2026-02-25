import { Properties } from '~/plugin-scaffold'

import { GroupTypeToColumnIndex, ProjectId, TeamId } from '../../types'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'

export function enrichPropertiesWithGroupTypes(properties: Properties, groupTypes: GroupTypeToColumnIndex): Properties {
    for (const [groupType, groupIdentifier] of Object.entries(properties.$groups || {})) {
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
    const resolvedTypes: GroupTypeToColumnIndex = {}
    for (const [groupType] of Object.entries(properties.$groups || {})) {
        const columnIndex = await groupTypeManager.fetchGroupTypeIndex(teamId, projectId, groupType)
        if (columnIndex !== null) {
            resolvedTypes[groupType] = columnIndex
        }
    }
    return enrichPropertiesWithGroupTypes(properties, resolvedTypes)
}
