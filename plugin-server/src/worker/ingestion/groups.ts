import { Properties } from '@posthog/plugin-scaffold'

import { TeamId } from '../../types'
import { GroupTypeManager } from './group-type-manager'

export async function addGroupProperties(
    teamId: TeamId,
    properties: Properties,
    groupTypeManager: GroupTypeManager
): Promise<Properties> {
    for (const [groupType, groupIdentifier] of Object.entries(properties.$groups || {})) {
        const columnIndex = await groupTypeManager.fetchGroupTypeIndex(teamId, groupType)
        if (columnIndex !== null) {
            // :TODO: Update event column instead
            properties[`$group_${columnIndex}`] = groupIdentifier
        }
    }
    return properties
}
