import { GroupTypeIndex, GroupTypeToColumnIndex, ProjectId, Team, TeamGroupRow, TeamId } from '../../types'
import { PostgresRouter, PostgresUse } from '../../utils/db/postgres'
import { timeoutGuard } from '../../utils/db/utils'
import { captureTeamEvent } from '../../utils/posthog'
import { status } from '../../utils/status'
import { getByAge } from '../../utils/utils'
import { TeamManager } from './team-manager'

/** How many unique group types to allow per team */
export const MAX_GROUP_TYPES_PER_TEAM = 5

const CHUNK_SIZE = 100

export class GroupTypeManager {
    private groupTypesCache: Map<ProjectId, [GroupTypeToColumnIndex, number]>
    private instanceSiteUrl: string

    constructor(private postgres: PostgresRouter, private teamManager: TeamManager, instanceSiteUrl?: string | null) {
        this.groupTypesCache = new Map()
        this.instanceSiteUrl = instanceSiteUrl || 'unknown'
    }

    // BaseEvent doesn't have project_id yet so still using team_id here.
    // TODO(eli): see if the underlying Kafka event payload does and we can add it (cc Ben)
    public async fetchGroupTypesIndicesForTeams(
        groupTeamIds: TeamId[]
    ): Promise<Record<number, GroupTypeToColumnIndex>> {
        const out: Record<number, GroupTypeToColumnIndex> = {}
        if (groupTeamIds.length === 0) {
            return out
        }

        const dedupedTeamIds = new Set(groupTeamIds)

        // first, capture already cached group types and their indexes
        const cachedTeamIds = new Set(
            Array.from(dedupedTeamIds).filter((teamId) => {
                const gtci = this.groupTypesCache.get(teamId as ProjectId) // HACK ALERT!! no way this is a good idea (cc Ben)
                if (gtci) {
                    gtci.forEach((entry) => {
                        // if it's a GroupTypeToColumnIndex, not a number, we can use it
                        if (typeof entry !== 'number') {
                            if (!out[teamId]) {
                                out[teamId] = entry
                            }
                        }
                    })
                    return true
                }
                return false
            })
        )

        // finally, figure out what we need to fetch from the DB, then do so in batches
        const teamIdsToFetch = Array.from(dedupedTeamIds.difference(cachedTeamIds))

        const handles: Promise<TeamGroupRow[]>[] = []
        for (let i = 0; i < teamIdsToFetch.length; i += CHUNK_SIZE) {
            const chunk = teamIdsToFetch.slice(i, i + CHUNK_SIZE)
            handles.push(this.fetchGroupTypeIndicesForTeams(chunk))
        }

        await Promise.all(handles).then((results) => {
            results.forEach((foundGTIs) =>
                foundGTIs.forEach((teamGroupRow) => {
                    if (!out[teamGroupRow.teamId]) {
                        out[teamGroupRow.teamId] = {}
                    }
                    out[teamGroupRow.teamId][teamGroupRow.groupName] = teamGroupRow.groupIndex as GroupTypeIndex
                })
            )
        })

        return out
    }

    // TODO(eli): convert to use ProjectId if we can add to ClickHouseEvent
    private async fetchGroupTypeIndicesForTeams(teamIds: TeamId[]): Promise<TeamGroupRow[]> {
        const result = await this.postgres
            .query<TeamGroupRow>(
                PostgresUse.COMMON_READ,
                `SELECT team_id, group_type, group_type_index FROM posthog_grouptypemapping WHERE team_id = ANY ($1)`,
                [teamIds],
                'findGroupTypeIndicesForTeams'
            )
            .catch((e) => {
                status.error('🔁', `Error fetching group type mappings`, { error: e.message })
                throw e
            })

        return result.rows
    }

    public async fetchGroupTypes(projectId: ProjectId): Promise<GroupTypeToColumnIndex> {
        const cachedGroupTypes = getByAge(this.groupTypesCache, projectId)
        if (cachedGroupTypes) {
            return cachedGroupTypes
        }

        const timeout = timeoutGuard(`Still running "fetchGroupTypes". Timeout warning after 30 sec!`)
        try {
            const { rows } = await this.postgres.query(
                PostgresUse.COMMON_WRITE, // TODO: can we get away with COMMON_READ here? cc Ben
                `SELECT * FROM posthog_grouptypemapping WHERE project_id = $1`,
                [projectId],
                'fetchGroupTypes'
            )

            const teamGroupTypes: GroupTypeToColumnIndex = {}

            for (const row of rows) {
                teamGroupTypes[row.group_type] = row.group_type_index
            }

            this.groupTypesCache.set(projectId, [teamGroupTypes, Date.now()])

            return teamGroupTypes
        } finally {
            clearTimeout(timeout)
        }
    }

    public async fetchGroupTypeIndex(
        teamId: TeamId,
        projectId: ProjectId,
        groupType: string
    ): Promise<GroupTypeIndex | null> {
        const groupTypes = await this.fetchGroupTypes(projectId)

        if (groupType in groupTypes) {
            return groupTypes[groupType]
        } else {
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
