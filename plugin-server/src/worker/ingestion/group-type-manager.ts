import { GroupTypeIndex, GroupTypeToColumnIndex, ProjectId, Team, TeamId } from '../../types'
import { timeoutGuard } from '../../utils/db/utils'
import { LazyLoader } from '../../utils/lazy-loader'
import { captureTeamEvent } from '../../utils/posthog'
import { TeamManager } from '../../utils/team-manager'
import { GroupRepository } from './groups/repositories/group-repository.interface'

/** How many unique group types to allow per team */
export const MAX_GROUP_TYPES_PER_TEAM = 5

export type GroupTypesByProjectId = Record<ProjectId, GroupTypeToColumnIndex>

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
                    const groupTypesByProject = await this.groupRepository.fetchGroupTypesByProjectIds(projectIdNumbers)

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

    public async fetchGroupTypeIndex(
        teamId: TeamId,
        projectId: ProjectId,
        groupType: string
    ): Promise<GroupTypeIndex | null> {
        const groupTypes = await this.fetchGroupTypes(projectId)
        if (groupType in groupTypes) {
            return groupTypes[groupType]
        }

        const [groupTypeIndex, isInsert] = await this.groupRepository.insertGroupType(
            teamId,
            projectId,
            groupType,
            Object.keys(groupTypes).length
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
