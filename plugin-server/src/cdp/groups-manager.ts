import { Hub, Team } from '../types'
import { PostgresUse } from '../utils/db/postgres'
import { GroupType, HogFunctionInvocationGlobals } from './types'

export type GroupsMap = Record<string, GroupType>
export type GroupsCache = Record<Team['id'], GroupsMap>

// Maps to the group type index for easy lookup like: { 'team_id:group_type': group_type_index }
type GroupIndexByTeamType = Record<string, number | undefined>

type Group = {
    id: string
    index: number
    type: string
    url: string
    properties: Record<string, any>
    teamId?: number
}

export class GroupsManager {
    constructor(private hub: Hub) {}

    private async filterTeamsWithGroups(teams: Team['id'][]): Promise<Team['id'][]> {
        const teamIds = await Promise.all(
            teams.map(async (teamId) => {
                if (await this.hub.organizationManager.hasAvailableFeature(teamId, 'group_analytics')) {
                    return teamId
                }
            })
        )

        return teamIds.filter((x) => x !== undefined) as Team['id'][]
    }

    private async fetchGroupTypesMapping(teams: Team['id'][]): Promise<GroupIndexByTeamType> {
        const teamsWithGroupAnalytics = await this.filterTeamsWithGroups(teams)

        const result = await this.hub.postgres.query(
            PostgresUse.COMMON_READ,
            `SELECT team_id, group_type, group_type_index FROM posthog_grouptypemapping WHERE team_id = ANY($1)`,
            [teamsWithGroupAnalytics],
            'fetchGroupTypes'
        )

        return result.rows.reduce(
            (acc, row) => ({
                ...acc,
                [`${row.team_id}:${row.group_type}`]: row.group_type_index,
            }),
            {} as GroupIndexByTeamType
        )
    }

    private async fetchGroupProperties(
        groups: Group[]
    ): Promise<
        { team_id: number; group_type_index: number; group_key: string; group_properties: Record<string, any> }[]
    > {
        const [teamIds, groupIndexes, groupKeys] = groups.reduce(
            (acc, group) => {
                acc[0].push(group.teamId!)
                acc[1].push(group.index)
                acc[2].push(group.id)
                return acc
            },
            [[], [], []] as [number[], number[], string[]]
        )
        // Load the group properties
        return (
            await this.hub.postgres.query(
                PostgresUse.COMMON_READ,
                `SELECT team_id, group_type_index, group_key, group_properties
            FROM posthog_group
            WHERE team_id = ANY($1) AND group_type_index = ANY($2) AND group_key = ANY($3)`,
                [teamIds, groupIndexes, groupKeys],
                'fetchGroups'
            )
        ).rows
    }

    /**
     * This function looks complex but is trying to be as optimized as possible.
     *
     * It iterates over the globals and creates "Group" objects, tracking them referentially in order to later load the properties.
     * Once loaded, the objects are mutated in place.
     */
    public async enrichGroups(items: HogFunctionInvocationGlobals[]): Promise<HogFunctionInvocationGlobals[]> {
        const itemsNeedingGroups = items.filter((x) => !x.groups)
        const byTeamType = await this.fetchGroupTypesMapping(
            Array.from(new Set(itemsNeedingGroups.map((global) => global.project.id)))
        )

        const groupsByTeamTypeId: Record<string, Group> = {}

        itemsNeedingGroups.forEach((item) => {
            const groupsProperty: Record<string, string> = item.event.properties['$groups'] || {}
            const groups: HogFunctionInvocationGlobals['groups'] = {}

            // Add the base group info without properties
            Object.entries(groupsProperty).forEach(([groupType, groupKey]) => {
                const groupIndex = byTeamType[`${item.project.id}:${groupType}`]

                if (typeof groupIndex === 'number') {
                    let group = groupsByTeamTypeId[`${item.project.id}:${groupIndex}:${groupKey}`]
                    if (!group) {
                        group = groupsByTeamTypeId[`${item.project.id}:${groupIndex}:${groupKey}`] = {
                            id: groupKey,
                            index: groupIndex,
                            type: groupType,
                            url: `${item.project.url}/groups/${groupIndex}/${encodeURIComponent(groupKey)}`,
                            properties: {},
                            teamId: item.project.id,
                        }
                    }

                    // Add to the groups to be enriched and the object here
                    groups[groupType] = group
                }
            })

            item.groups = groups

            console.log(item)
        })
        // Load the group properties
        const groupsFromDatabase = await this.fetchGroupProperties(Object.values(groupsByTeamTypeId))

        // Add the properties to all the groups
        groupsFromDatabase.forEach((row) => {
            const group = groupsByTeamTypeId[`${row.team_id}:${row.group_type_index}:${row.group_key}`]

            console.log(row, group)
            if (group) {
                group.properties = row.group_properties
                delete group.teamId // We don't want it in the final payload
            }
        })

        console.log(items)

        return items
    }
}
