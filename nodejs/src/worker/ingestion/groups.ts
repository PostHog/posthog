import { Properties } from '@posthog/plugin-scaffold'

import { PersonGroupKeys, ProjectId, TeamId } from '../../types'
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

/**
 * Extracts group keys from event properties for updating person records.
 * This enables JOINing persons to groups for mixed user+group feature flag targeting.
 *
 * @returns PersonGroupKeys with group keys extracted from $groups or empty strings if not present
 */
export async function extractGroupKeysForPerson(
    teamId: TeamId,
    projectId: ProjectId,
    properties: Properties,
    groupTypeManager: GroupTypeManager
): Promise<Partial<PersonGroupKeys>> {
    const groupKeys: Partial<PersonGroupKeys> = {}
    const groups = properties.$groups

    if (!groups || typeof groups !== 'object') {
        return groupKeys
    }

    for (const [groupType, groupIdentifier] of Object.entries(groups)) {
        const columnIndex = await groupTypeManager.fetchGroupTypeIndex(teamId, projectId, groupType)
        if (columnIndex !== null && groupIdentifier !== undefined) {
            const key = `group_${columnIndex}_key` as keyof PersonGroupKeys
            groupKeys[key] = String(groupIdentifier)
        }
    }

    return groupKeys
}
