import { GroupTypeIndex, GroupTypeToColumnIndex, Team, TeamId } from '../../types'
import { PostgresRouter, PostgresUse } from '../../utils/db/postgres'
import { timeoutGuard } from '../../utils/db/utils'
import { captureTeamEvent } from '../../utils/posthog'
import { getByAge } from '../../utils/utils'
import { TeamManager } from './team-manager'

/** How many unique group types to allow per team */
export const MAX_GROUP_TYPES_PER_TEAM = 5

export class GroupTypeManager {
    private groupTypesCache: Map<number, [GroupTypeToColumnIndex, number]>
    private instanceSiteUrl: string

    constructor(private postgres: PostgresRouter, private teamManager: TeamManager, instanceSiteUrl?: string | null) {
        this.groupTypesCache = new Map()
        this.instanceSiteUrl = instanceSiteUrl || 'unknown'
    }

    public async fetchGroupTypes(teamId: TeamId): Promise<GroupTypeToColumnIndex> {
        const cachedGroupTypes = getByAge(this.groupTypesCache, teamId)
        if (cachedGroupTypes) {
            return cachedGroupTypes
        }

        const timeout = timeoutGuard(`Still running "fetchGroupTypes". Timeout warning after 30 sec!`)
        try {
            const { rows } = await this.postgres.query(
                PostgresUse.COMMON_WRITE,
                `SELECT * FROM posthog_grouptypemapping WHERE team_id = $1`,
                [teamId],
                'fetchGroupTypes'
            )

            const teamGroupTypes: GroupTypeToColumnIndex = {}

            for (const row of rows) {
                teamGroupTypes[row.group_type] = row.group_type_index
            }

            this.groupTypesCache.set(teamId, [teamGroupTypes, Date.now()])

            return teamGroupTypes
        } finally {
            clearTimeout(timeout)
        }
    }

    public async fetchGroupTypeIndex(teamId: TeamId, groupType: string): Promise<GroupTypeIndex | null> {
        const groupTypes = await this.fetchGroupTypes(teamId)

        if (groupType in groupTypes) {
            return groupTypes[groupType]
        } else {
            const [groupTypeIndex, isInsert] = await this.insertGroupType(
                teamId,
                groupType,
                Object.keys(groupTypes).length
            )
            if (groupTypeIndex !== null) {
                this.groupTypesCache.delete(teamId)
            }

            if (isInsert && groupTypeIndex !== null) {
                this.captureGroupTypeInsert(teamId, groupType, groupTypeIndex)
            }
            return groupTypeIndex
        }
    }

    public async insertGroupType(
        teamId: TeamId,
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
                INSERT INTO posthog_grouptypemapping (team_id, group_type, group_type_index)
                VALUES ($1, $2, $3)
                ON CONFLICT DO NOTHING
                RETURNING group_type_index
            )
            SELECT group_type_index, 1 AS is_insert  FROM insert_result
            UNION
            SELECT group_type_index, 0 AS is_insert FROM posthog_grouptypemapping WHERE team_id = $1 AND group_type = $2;
            `,
            [teamId, groupType, index],
            'insertGroupType'
        )

        if (insertGroupTypeResult.rows.length == 0) {
            return await this.insertGroupType(teamId, groupType, index + 1)
        }

        const { group_type_index, is_insert } = insertGroupTypeResult.rows[0]

        return [group_type_index, is_insert === 1]
    }

    private captureGroupTypeInsert(teamId: TeamId, groupType: string, groupTypeIndex: GroupTypeIndex) {
        const team: Team | null = this.teamManager.getTeam(teamId)
        if (team) {
            captureTeamEvent(team, 'group type ingested', { groupType, groupTypeIndex })
        }
    }
}
