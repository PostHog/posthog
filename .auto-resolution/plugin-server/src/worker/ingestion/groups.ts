import { Properties } from '@posthog/plugin-scaffold'

import { ProjectId, TeamId } from '../../types'
import { GroupTypeManager } from './group-type-manager'

export async function addGroupProperties(
    teamId: TeamId,
    projectId: ProjectId,
    properties: Properties,
    groupTypeManager: GroupTypeManager
): Promise<Properties> {
    for (const [groupType, groupIdentifier] of Object.entries(properties.$groups || {})) {
        const columnIndex = await groupTypeManager.fetchGroupTypeIndex(teamId, projectId, groupType)
        if (columnIndex !== null) {
            // :TODO: Update event column instead
            properties[`$group_${columnIndex}`] = groupIdentifier
        }
    }
    return properties
}
