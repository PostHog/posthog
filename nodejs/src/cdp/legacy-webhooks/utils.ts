import { GroupTypeIndex, GroupTypeToColumnIndex, PostIngestionEvent, TeamId } from '~/types'
import { TeamManager } from '~/utils/team-manager'
import { GroupTypeManager } from '~/worker/ingestion/group-type-manager'
import { GroupRepository } from '~/worker/ingestion/groups/repositories/group-repository.interface'

export async function addGroupPropertiesToPostIngestionEvent(
    event: PostIngestionEvent,
    groupTypeManager: GroupTypeManager,
    teamManager: TeamManager,
    groupRepository: GroupRepository
): Promise<PostIngestionEvent> {
    let groupTypes: GroupTypeToColumnIndex | null = null
    if (await teamManager.hasAvailableFeature(event.teamId, 'group_analytics')) {
        // If the organization has group analytics enabled then we enrich the event with group data
        groupTypes = await groupTypeManager.fetchGroupTypes(event.projectId)
    }

    let groups: PostIngestionEvent['groups'] = undefined
    if (groupTypes) {
        groups = {}

        for (const [groupType, columnIndex] of Object.entries(groupTypes)) {
            const groupKey = (event.properties[`$groups`] || {})[groupType]
            if (!groupKey) {
                continue
            }

            const group = await groupRepository.fetchGroup(
                event.teamId as TeamId,
                columnIndex as GroupTypeIndex,
                groupKey,
                { useReadReplica: true }
            )

            const groupProperties = group ? group.group_properties : {}

            if (groupKey && groupProperties) {
                groups[groupType] = {
                    index: columnIndex,
                    key: groupKey,
                    type: groupType,
                    properties: groupProperties,
                }
            }
        }
    }

    return {
        ...event,
        groups,
    }
}
