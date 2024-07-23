import { Hub, Team } from '../types'
import { PostgresUse } from '../utils/db/postgres'
import { GroupType, HogFunctionInvocationGlobals } from './types'

export type GroupsMap = Record<string, GroupType>
export type GroupsCache = Record<Team['id'], GroupsMap>

// Maps to the group type index for easy lookup like: { 'team_id:group_type': group_type_index }
type GroupIndexByTeamType = Record<string, number | undefined>

export class GroupsManager {
    constructor(private hub: Hub) {}

    private async getGroupIndexByTeamType(teams: Team['id'][]): Promise<GroupIndexByTeamType> {
        const result = await this.hub.postgres.query(
            PostgresUse.COMMON_READ,
            `SELECT team_id, group_type, group_type_index FROM posthog_grouptypemapping WHERE team_id = ANY($1)`,
            [teams],
            'fetchGroupTypes'
        )

        const rows = result.rows

        return rows.reduce((acc, row) => {
            acc[`${row.team_id}:${row.group_type}`] = row.group_type_index
            return acc
        })
    }

    public async enrichGroups(globals: HogFunctionInvocationGlobals[]): Promise<HogFunctionInvocationGlobals[]> {
        // Optimized function for fetching a range of groups
        // TODO: Before getting here filter to only enrich the globals where hog functions will use `groups`

        const globalsNeedingGroups = globals.filter((globals) => !globals.groups)
        const teamIds = Array.from(new Set(globalsNeedingGroups.map((global) => global.project.id)))
        const groupIndexByTeamType = await this.getGroupIndexByTeamType(teamIds)

        // Keyed by `team_id:group_type:group_key`
        const loadedGroupsMapping: Record<
            string,
            { groupKey: string; groupIndex: number; teamId: number; properties?: Record<string, any> }
        > = {}

        globalsNeedingGroups.forEach((globals) => {
            const groupsProperty: Record<string, string> = globals.event.properties['$groups'] || {}

            const groups: HogFunctionInvocationGlobals['groups'] = {}

            // Add the base group info without properties
            Object.entries(groupsProperty).forEach(([groupType, groupKey]) => {
                const groupIndex = groupIndexByTeamType[`${globals.project.id}:${groupType}`]

                if (typeof groupIndex === 'number') {
                    groups[groupType] = {
                        id: groupKey,
                        index: groupIndex,
                        type: groupType,
                        url: `${globals.project.url}/groups/${groupIndex}/${encodeURIComponent(groupKey)}`,
                        properties: {},
                    }
                    loadedGroupsMapping[`${globals.project.id}:${groupIndex}:${groupKey}`] = {
                        groupKey,
                        groupIndex,
                        teamId: globals.project.id,
                    }
                }
            })
        })

        const groupKeysToLoad = Object.values(loadedGroupsMapping).map((group) => group.groupKey)
        const groupIndexToLoad = Object.values(loadedGroupsMapping).map((group) => group.groupIndex)
        const teamIdsToLoad = Object.values(loadedGroupsMapping).map((group) => group.teamId)

        // Load the group properties
        const res = await this.hub.postgres.query(
            PostgresUse.COMMON_READ,
            `SELECT team_id, group_type_index, group_key, group_properties
            FROM posthog_group
            WHERE team_id = ANY($1) AND group_type_index = ANY($2) AND group_key = ANY($3)`,
            [teamIdsToLoad, groupIndexToLoad, groupKeysToLoad],
            'fetchGroups'
        )

        res.rows.forEach((row) => {
            // TODO: I think we need the reverse mapping as well :(
            const group = loadedGroupsMapping[`${row.team_id}:${row.group_type_index}:${row.group_key}`]
            if (group) {
                group.properties = row.group_properties
            }
        })
        return globals
    }
}
