import { DateTime } from 'luxon'

import { GroupTypeManager } from '~/common/groups/group-type-manager'
import { sanitizeString } from '~/common/utils/db/utils'
import { Properties } from '~/plugin-scaffold'
import { GroupTypeToColumnIndex, ProjectId, TeamId } from '~/types'

/**
 * Extract the group identity from a $groupidentify event's properties. Owns the
 * presence checks (falsy $group_type / $group_key are skipped) and the exact key
 * normalization the group store is keyed by, so every reader and writer of the
 * group cache — the upsert path and the prefetch path — lands on a byte-identical
 * key. Group-type-index resolution intentionally stays out: the upsert path may
 * insert a new mapping while the prefetch path is read-only.
 */
export function extractGroupIdentify(
    properties: Properties | undefined
): { groupType: string; groupKey: string } | null {
    if (!properties || !properties['$group_type'] || !properties['$group_key']) {
        return null
    }
    return {
        groupType: properties['$group_type'],
        groupKey: sanitizeString(properties['$group_key'].toString()),
    }
}

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

export async function addGroupProperties(
    teamId: TeamId,
    projectId: ProjectId,
    properties: Properties,
    groupTypeManager: GroupTypeManager,
    eventTimestamp: DateTime
): Promise<Properties> {
    const groups = properties.$groups
    if (typeof groups !== 'object' || groups === null || Array.isArray(groups)) {
        return properties
    }
    const resolvedTypes: GroupTypeToColumnIndex = {}
    for (const [groupType] of Object.entries(groups)) {
        const columnIndex = await groupTypeManager.fetchGroupTypeIndex(teamId, projectId, groupType, eventTimestamp)
        if (columnIndex !== null) {
            resolvedTypes[groupType] = columnIndex
        }
    }
    return enrichPropertiesWithGroupTypes(properties, resolvedTypes)
}
