import { GroupTypeIndex, GroupTypeToColumnIndex, Team, TeamId } from '../../types'
import { PostgresRouter, PostgresUse } from '../../utils/db/postgres'
import { timeoutGuard } from '../../utils/db/utils'
import { LazyLoader } from '../../utils/lazy-loader'
import { captureTeamEvent } from '../../utils/posthog'
import { TeamManager } from './team-manager'

/** How many unique group types to allow per team */
export const MAX_GROUP_TYPES_PER_TEAM = 5

export type GroupTypesByTeamId = Record<TeamId, GroupTypeToColumnIndex>

export class GroupTypeManager {
    private loader: LazyLoader<GroupTypeToColumnIndex>

    constructor(private postgres: PostgresRouter, private teamManager: TeamManager) {
        this.loader = new LazyLoader({
            name: 'GroupTypeManager',
            refreshAge: 30_000, // 30 seconds
            refreshNullAge: 30_000, // 30 seconds
            refreshJitterMs: 0,
            loader: async (teamIds: string[]) => {
                const response: Record<string, GroupTypeToColumnIndex> = {}
                const timeout = timeoutGuard(`Still running "fetchGroupTypes". Timeout warning after 30 sec!`)
                try {
                    const { rows } = await this.postgres.query(
                        PostgresUse.COMMON_READ,
                        `SELECT * FROM posthog_grouptypemapping WHERE team_id = ANY($1)`,
                        [Array.from(teamIds)],
                        'fetchGroupTypes'
                    )
                    for (const row of rows) {
                        const groupTypes = (response[row.team_id] = response[row.team_id] ?? {})
                        groupTypes[row.group_type] = row.group_type_index
                    }
                    for (const teamId of teamIds) {
                        response[teamId] = response[teamId] ?? {}
                    }
                } finally {
                    clearTimeout(timeout)
                }
                return response
            },
        })
    }

    public async fetchGroupTypes(team: Team): Promise<GroupTypeToColumnIndex> {
        return (await this.loader.get(team.root_team_id.toString())) ?? {}
    }

    public async fetchGroupTypeIndex(team: Team, groupType: string): Promise<GroupTypeIndex | null> {
        const groupTypes = await this.fetchGroupTypes(team)
        if (groupType in groupTypes) {
            return groupTypes[groupType]
        }

        const [groupTypeIndex, isInsert] = await this.insertGroupType(team, groupType, Object.keys(groupTypes).length)
        if (groupTypeIndex !== null) {
            this.loader.markForRefresh(team.root_team_id.toString())
        }

        if (isInsert && groupTypeIndex !== null) {
            // TODO: Is the `group type ingested` event being valuable? If not, we can remove
            // `captureGroupTypeInsert()`. If yes, we should move this capture to use the project instead of team
            await this.captureGroupTypeInsert(team.root_team_id, groupType, groupTypeIndex)
        }
        return groupTypeIndex
    }

    public async insertGroupType(
        team: Team,
        groupType: string,
        index: number
    ): Promise<[GroupTypeIndex | null, boolean]> {
        if (index >= MAX_GROUP_TYPES_PER_TEAM) {
            return [null, false]
        }

        // NOTE: We used to use "project_id" here but we moved to remove it.
        // In the interim we write both the root_team_id and the project_id.
        const insertGroupTypeResult = await this.postgres.query(
            PostgresUse.COMMON_WRITE,
            // This looks complex but its all about returning multiple bits of info in one query
            // * Insert the group type if it doesn't exist for this index
            // * Return the group type index if we inserted it, otherwise try and find the existing index and return that
            // * Return nothing if it doesn't exist
            // Then in code we can know if no rows were returned we should try a higher index as a different process got there first.
            `
            WITH insert_result AS (
                INSERT INTO posthog_grouptypemapping (team_id, project_id, group_type, group_type_index)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT DO NOTHING
                RETURNING group_type_index
            )
            SELECT group_type_index, 1 AS is_insert FROM insert_result
            UNION
            SELECT group_type_index, 0 AS is_insert FROM posthog_grouptypemapping WHERE team_id = $1 AND group_type = $3;
            `,
            [team.root_team_id, team.root_team_id, groupType, index],
            'insertGroupType'
        )

        if (insertGroupTypeResult.rows.length == 0) {
            return await this.insertGroupType(team, groupType, index + 1)
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
