import { GroupTypeIndex, GroupTypeToColumnIndex, PostIngestionEvent, ProjectId, TeamId } from '~/types'
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
                { useReadReplica: true, callerTag: 'cdp/legacy-webhooks-group-enrichment' }
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

type GroupLookupKey = `${number}:${number}:${string}`

function makeGroupLookupKey(teamId: number, groupTypeIndex: number, groupKey: string): GroupLookupKey {
    return `${teamId}:${groupTypeIndex}:${groupKey}`
}

export async function addGroupPropertiesToPostIngestionEventsBatch(
    events: PostIngestionEvent[],
    groupTypeManager: GroupTypeManager,
    teamManager: TeamManager,
    groupRepository: GroupRepository
): Promise<PostIngestionEvent[]> {
    if (events.length === 0) {
        return []
    }

    const uniqueTeamIds = [...new Set(events.map((e) => e.teamId))]
    const teamHasGroupAnalytics = new Map<number, boolean>()
    await Promise.all(
        uniqueTeamIds.map(async (teamId) => {
            const has = await teamManager.hasAvailableFeature(teamId, 'group_analytics')
            teamHasGroupAnalytics.set(teamId, has)
        })
    )

    const projectIdsNeedingGroups = new Set<ProjectId>()
    for (const event of events) {
        if (teamHasGroupAnalytics.get(event.teamId)) {
            projectIdsNeedingGroups.add(event.projectId)
        }
    }

    if (projectIdsNeedingGroups.size === 0) {
        return events
    }

    const groupTypesByProject = await groupTypeManager.fetchGroupTypesForProjects(projectIdsNeedingGroups)

    const allTeamIds: TeamId[] = []
    const allGroupTypeIndexes: GroupTypeIndex[] = []
    const allGroupKeys: string[] = []
    const seenKeys = new Set<GroupLookupKey>()

    type EventGroupNeed = { groupType: string; columnIndex: GroupTypeIndex; groupKey: string }
    const eventGroupNeeds: (EventGroupNeed[] | null)[] = []

    for (const event of events) {
        if (!teamHasGroupAnalytics.get(event.teamId)) {
            eventGroupNeeds.push(null)
            continue
        }

        const groupTypes = groupTypesByProject[event.projectId]
        if (!groupTypes || Object.keys(groupTypes).length === 0) {
            eventGroupNeeds.push([])
            continue
        }

        const needs: EventGroupNeed[] = []
        for (const [groupType, columnIndex] of Object.entries(groupTypes)) {
            const groupKey = (event.properties['$groups'] || {})[groupType]
            if (!groupKey) {
                continue
            }

            needs.push({ groupType, columnIndex: columnIndex as GroupTypeIndex, groupKey })

            const lookupKey = makeGroupLookupKey(event.teamId, columnIndex, groupKey)
            if (!seenKeys.has(lookupKey)) {
                seenKeys.add(lookupKey)
                allTeamIds.push(event.teamId as TeamId)
                allGroupTypeIndexes.push(columnIndex as GroupTypeIndex)
                allGroupKeys.push(groupKey)
            }
        }

        eventGroupNeeds.push(needs)
    }

    const groupResults =
        allTeamIds.length > 0
            ? await groupRepository.fetchGroupsByKeys(
                  allTeamIds,
                  allGroupTypeIndexes,
                  allGroupKeys,
                  'cdp/legacy-webhooks-group-enrichment'
              )
            : []

    const groupPropertiesMap = new Map<GroupLookupKey, Record<string, any>>()
    for (const result of groupResults) {
        const key = makeGroupLookupKey(result.team_id, result.group_type_index, result.group_key)
        groupPropertiesMap.set(key, result.group_properties)
    }

    return events.map((event, i) => {
        const needs = eventGroupNeeds[i]

        if (needs === null) {
            return event
        }

        const groups: PostIngestionEvent['groups'] = {}
        for (const { groupType, columnIndex, groupKey } of needs) {
            const key = makeGroupLookupKey(event.teamId, columnIndex, groupKey)
            const properties = groupPropertiesMap.get(key) ?? {}
            groups[groupType] = {
                index: columnIndex,
                key: groupKey,
                type: groupType,
                properties,
            }
        }

        return { ...event, groups }
    })
}
