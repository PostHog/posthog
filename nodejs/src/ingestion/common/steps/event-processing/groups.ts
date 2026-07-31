import { DateTime } from 'luxon'

import { GroupTypeManager } from '~/common/groups/group-type-manager'
import { Properties } from '~/plugin-scaffold'
import { GroupTypeToColumnIndex, ProjectId, TeamId } from '~/types'

export function enrichPropertiesWithGroupTypes(
    properties: Properties,
    groupTypesToColumnIndex: GroupTypeToColumnIndex
): Properties {
    const groups = properties.$groups
    if (typeof groups !== 'object' || groups === null || Array.isArray(groups)) {
        return properties
    }
    for (const [groupType, groupIdentifier] of Object.entries(groups)) {
        if (groupType in groupTypesToColumnIndex) {
            // :TODO: Update event column instead
            const groupIndex = groupTypesToColumnIndex[groupType]
            properties[`$group_${groupIndex}`] = groupIdentifier
        }
    }
    return properties
}

export interface AddGroupPropertiesResult {
    properties: Properties
    /**
     * Group types from `$groups` that couldn't be resolved to a column index —
     * `fetchGroupTypeIndex` returns null only once the project already has
     * `MAX_GROUP_TYPES_PER_TEAM` group types registered (group-type-manager.ts),
     * since an already-known group type resolves via the fast lookup path and
     * never reaches that null branch. So a null result always means the team hit
     * the cap, never some other failure.
     */
    droppedGroupTypes: string[]
}

export async function addGroupProperties(
    teamId: TeamId,
    projectId: ProjectId,
    properties: Properties,
    groupTypeManager: GroupTypeManager,
    eventTimestamp: DateTime
): Promise<AddGroupPropertiesResult> {
    const groups = properties.$groups
    if (typeof groups !== 'object' || groups === null || Array.isArray(groups)) {
        return { properties, droppedGroupTypes: [] }
    }
    const resolvedTypes: GroupTypeToColumnIndex = {}
    const droppedGroupTypes: string[] = []
    for (const [groupType] of Object.entries(groups)) {
        const columnIndex = await groupTypeManager.fetchGroupTypeIndex(teamId, projectId, groupType, eventTimestamp)
        if (columnIndex !== null) {
            resolvedTypes[groupType] = columnIndex
        } else {
            droppedGroupTypes.push(groupType)
        }
    }
    return { properties: enrichPropertiesWithGroupTypes(properties, resolvedTypes), droppedGroupTypes }
}
