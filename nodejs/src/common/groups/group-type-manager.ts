import { DateTime } from 'luxon'

import { GroupRepository } from '~/common/groups/repositories/group-repository.interface'
import { timeoutGuard } from '~/common/utils/db/utils'
import { LazyLoader } from '~/common/utils/lazy-loader'
import { captureTeamEvent } from '~/common/utils/posthog'
import { TeamManager } from '~/common/utils/team-manager'
import { GroupTypeIndex, GroupTypeToColumnIndex, GroupTypesByProjectId, ProjectId, Team, TeamId } from '~/types'

/** How many unique group types to allow per team */
export const MAX_GROUP_TYPES_PER_TEAM = 5

export class GroupTypeManager {
    private loader: LazyLoader<GroupTypeToColumnIndex>

    constructor(
        private groupRepository: GroupRepository,
        private teamManager: TeamManager
    ) {
        this.loader = new LazyLoader({
            name: 'GroupTypeManager',
            refreshAgeMs: 30_000, // 30 seconds
            refreshJitterMs: 0,
            loader: async (projectIds: string[]) => {
                const response: Record<string, GroupTypeToColumnIndex> = {}
                const timeout = timeoutGuard(`Still running "fetchGroupTypes". Timeout warning after 30 sec!`)
                try {
                    const projectIdNumbers = projectIds.map((id) => parseInt(id) as ProjectId)
                    const groupTypesByProject = await this.groupRepository.fetchGroupTypesByProjectIds(
                        projectIdNumbers,
                        'ingestion/group-type-resolution'
                    )

                    for (const [projectIdStr, groupTypes] of Object.entries(groupTypesByProject)) {
                        const groupTypeMapping: GroupTypeToColumnIndex = {}
                        for (const groupType of groupTypes) {
                            groupTypeMapping[groupType.group_type] = groupType.group_type_index
                        }
                        response[projectIdStr] = groupTypeMapping
                    }

                    // Ensure all requested project IDs have an entry, even if empty
                    for (const projectId of projectIds) {
                        response[projectId] = response[projectId] ?? {}
                    }
                } finally {
                    clearTimeout(timeout)
                }
                return response
            },
        })
    }

    public async fetchGroupTypes(projectId: ProjectId): Promise<GroupTypeToColumnIndex> {
        return (await this.loader.get(projectId.toString())) ?? {}
    }

    /**
     * Resolve a group type to its column index from the cached mapping only — never creates a
     * mapping. Own-property + type guarded: the mapping is a plain object, so an
     * attacker-supplied name like "__proto__" or "constructor" would otherwise resolve to an
     * inherited non-numeric value and poison downstream SQL parameters.
     */
    public async lookupGroupTypeIndex(projectId: ProjectId, groupType: string): Promise<GroupTypeIndex | null> {
        const groupTypes = await this.fetchGroupTypes(projectId)
        const groupTypeIndex = Object.hasOwn(groupTypes, groupType) ? groupTypes[groupType] : undefined
        return typeof groupTypeIndex === 'number' ? groupTypeIndex : null
    }

    public async fetchGroupTypeIndex(
        teamId: TeamId,
        projectId: ProjectId,
        groupType: string,
        eventTimestamp: DateTime
    ): Promise<GroupTypeIndex | null> {
        const existingIndex = await this.lookupGroupTypeIndex(projectId, groupType)
        if (existingIndex !== null) {
            return existingIndex
        }

        const groupTypes = await this.fetchGroupTypes(projectId)

        const usedIndexes = new Set(Object.values(groupTypes))
        if (usedIndexes.size >= MAX_GROUP_TYPES_PER_TEAM) {
            return null
        }

        let nextAvailableIndex = 0
        while (usedIndexes.has(nextAvailableIndex as GroupTypeIndex)) {
            nextAvailableIndex++
        }

        // Use the triggering event's timestamp as the mapping's created_at, so historical imports
        // register the group type as of the event rather than wall-clock now (which would mask them).
        const [groupTypeIndex, isInsert] = await this.groupRepository.insertGroupType(
            teamId,
            projectId,
            groupType,
            nextAvailableIndex,
            eventTimestamp
        )
        if (groupTypeIndex !== null) {
            this.loader.markForRefresh(projectId.toString())
        }

        if (isInsert && groupTypeIndex !== null) {
            // TODO: Is the `group type ingested` event being valuable? If not, we can remove
            // `captureGroupTypeInsert()`. If yes, we should move this capture to use the project instead of team
            await this.captureGroupTypeInsert(teamId, groupType, groupTypeIndex)
        }
        return groupTypeIndex
    }

    public async fetchGroupTypesForProjects(projectIds: ProjectId[] | Set<ProjectId>): Promise<GroupTypesByProjectId> {
        const results = await this.loader.getMany(Array.from(projectIds).map((id) => id.toString()))

        return Object.fromEntries(
            Object.entries(results).map(([projectId, groupTypes]) => [projectId, groupTypes ?? {}])
        )
    }

    private async captureGroupTypeInsert(teamId: TeamId, groupType: string, groupTypeIndex: GroupTypeIndex) {
        const team: Team | null = await this.teamManager.getTeam(teamId)

        if (!team) {
            return
        }

        captureTeamEvent(team, 'group type ingested', { groupType, groupTypeIndex })
    }
}
