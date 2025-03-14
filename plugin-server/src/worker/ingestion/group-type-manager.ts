import { GroupTypeIndex, GroupTypeToColumnIndex, ProjectId, Team, TeamId } from '../../types'
import { PostgresRouter, PostgresUse } from '../../utils/db/postgres'
import { timeoutGuard } from '../../utils/db/utils'
import { captureTeamEvent } from '../../utils/posthog'
import { getByAge } from '../../utils/utils'
import { TeamManager } from './team-manager'

/** How many unique group types to allow per team */
export const MAX_GROUP_TYPES_PER_TEAM = 5

export type GroupTypesByProjectId = Record<ProjectId, GroupTypeToColumnIndex>

export class GroupTypeManager {
    private groupTypesCache: Map<ProjectId, [GroupTypeToColumnIndex, number]>

    constructor(private postgres: PostgresRouter, private teamManager: TeamManager) {
        this.groupTypesCache = new Map()
    }

    public async fetchGroupTypes(projectId: ProjectId): Promise<GroupTypeToColumnIndex | null> {
        const response = await this.fetchGroupTypesForProjects([projectId])
        return response[projectId]
    }

    public async fetchGroupTypesForProjects(projectIds: ProjectId[] | Set<ProjectId>): Promise<GroupTypesByProjectId> {
        const projectIdsSet = new Set(projectIds)
        const projectIdsToLoad = new Set<ProjectId>()
        const response: GroupTypesByProjectId = {}

        for (const projectId of projectIdsSet) {
            const cachedGroupTypes = getByAge(this.groupTypesCache, projectId)

            response[projectId] = cachedGroupTypes ?? {}

            if (!cachedGroupTypes) {
                projectIdsToLoad.add(projectId)
            }
        }

        if (projectIdsToLoad.size === 0) {
            return response
        }

        const timeout = timeoutGuard(`Still running "fetchGroupTypes". Timeout warning after 30 sec!`)
        try {
            const { rows } = await this.postgres.query(
                PostgresUse.COMMON_READ,
                `SELECT * FROM posthog_grouptypemapping WHERE project_id = ANY($1)`,
                [Array.from(projectIdsToLoad)],
                'fetchGroupTypes'
            )

            for (const row of rows) {
                const groupTypes = (response[row.project_id] = response[row.project_id] ?? {})
                groupTypes[row.group_type] = row.group_type_index
            }

            for (const projectId of projectIdsToLoad) {
                response[projectId] = response[projectId] ?? {}
                this.groupTypesCache.set(projectId, [response[projectId], Date.now()])
            }
        } finally {
            clearTimeout(timeout)
        }

        return response
    }

    public async fetchGroupTypeIndex(
        teamId: TeamId,
        projectId: ProjectId,
        groupType: string
    ): Promise<GroupTypeIndex | null> {
        const groupTypes = (await this.fetchGroupTypes(projectId)) ?? {}

        if (groupType in groupTypes) {
            return groupTypes[groupType]
        }

        const [groupTypeIndex, isInsert] = await this.insertGroupType(
            teamId,
            projectId,
            groupType,
            Object.keys(groupTypes).length
        )
        if (groupTypeIndex !== null) {
            this.groupTypesCache.delete(projectId)
        }

        if (isInsert && groupTypeIndex !== null) {
            // TODO: Is the `group type ingested` event being valuable? If not, we can remove
            // `captureGroupTypeInsert()`. If yes, we should move this capture to use the project instead of team
            await this.captureGroupTypeInsert(teamId, groupType, groupTypeIndex)
        }
        return groupTypeIndex
    }

    public async insertGroupType(
        teamId: TeamId,
        projectId: ProjectId,
        groupType: string,
        index: number
    ): Promise<[GroupTypeIndex | null, boolean]> {
        if (index >= MAX_GROUP_TYPES_PER_TEAM) {
            return [null, false]
        }

        const insertGroupTypeResult = await this.postgres.query(
            PostgresUse.COMMON_WRITE,
            `
            WITH insert_result AS (
                INSERT INTO posthog_grouptypemapping (team_id, project_id, group_type, group_type_index)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT DO NOTHING
                RETURNING group_type_index
            )
            SELECT group_type_index, 1 AS is_insert FROM insert_result
            UNION
            SELECT group_type_index, 0 AS is_insert FROM posthog_grouptypemapping WHERE project_id = $2 AND group_type = $3;
            `,
            [teamId, projectId, groupType, index],
            'insertGroupType'
        )

        if (insertGroupTypeResult.rows.length == 0) {
            return await this.insertGroupType(teamId, projectId, groupType, index + 1)
        }

        const { group_type_index, is_insert } = insertGroupTypeResult.rows[0]

        return [group_type_index, is_insert === 1]
    }

    private async captureGroupTypeInsert(teamId: TeamId, groupType: string, groupTypeIndex: GroupTypeIndex) {
        const team: Team | null = await this.teamManager.fetchTeam(teamId)

        if (!team) {
            return
        }

        captureTeamEvent(team, 'group type ingested', { groupType, groupTypeIndex })
    }
}
