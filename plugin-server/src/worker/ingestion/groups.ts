import { Properties } from '@posthog/plugin-scaffold'

import { TeamId } from '../../types'
import { status } from '../../utils/status'
import { GroupTypeManager } from './group-type-manager'

export async function getGroupColumns(
    teamId: TeamId,
    properties: Properties,
    groupTypeManager: GroupTypeManager
): Promise<Record<string, string>> {
    const result: Record<string, string> = {}

    if (typeof properties.$groups !== 'object') {
        status.info('🔔', "Couldn't event parse properties.$groups information, likely malformed. Ignoring", {
            properties,
        })
        return {}
    }

    for (const [groupType, groupIdentifier] of Object.entries(properties.$groups)) {
        const columnIndex = await groupTypeManager.fetchGroupTypeIndex(teamId, groupType)
        if (columnIndex !== null) {
            result[`group_${columnIndex}`] = (groupIdentifier as any).toString()
        }
    }

    return result
}
