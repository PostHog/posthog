import LRUCache from 'lru-cache'

import { Hub, Team } from '../../../types'
import { PostgresUse } from '../../../utils/db/postgres'
import { GroupType, HogFunctionInvocationGlobals } from '../../types'

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

const GROUP_TYPES_CACHE_AGE_MS = 60 * 10 * 1000 // 10 minutes

export class GroupsManagerService {
    groupTypesMappingCache: LRUCache<number, { type: string; index: number }[]>

    constructor(private hub: Hub) {
        // There is only 5 per team so we can have a very high cache and a very long cooldown
        this.groupTypesMappingCache = new LRUCache({ max: 1_000_000, maxAge: GROUP_TYPES_CACHE_AGE_MS })
    }

    private async filterTeamsWithGroups(teams: Team['id'][]): Promise<Team['id'][]> {
        const teamIds = await Promise.all(
            teams.map(async (teamId) => {
                if (await this.hub.teamManager.hasAvailableFeature(teamId, 'group_analytics')) {
                    return teamId
                }
            })
        )

        return teamIds.filter((x) => x !== undefined) as Team['id'][]
    }

    private async fetchGroupTypesMapping(teams: Team['id'][]): Promise<GroupIndexByTeamType> {
        // Get from cache otherwise load and save
        const teamsWithGroupAnalytics = await this.filterTeamsWithGroups(teams)

        // Load teams from cache where possible
        // Any teams that aren't in the cache we load from the DB, and then add to the cache

        const groupTypesMapping: GroupIndexByTeamType = {}

        // Load the cached values so we definitely have them
        teamsWithGroupAnalytics.forEach((teamId) => {
            const cached = this.groupTypesMappingCache.get(teamId)

            if (cached) {
                cached.forEach((row) => {
                    groupTypesMapping[`${teamId}:${row.type}`] = row.index
                })
            }
        })

        const teamsToLoad = teamsWithGroupAnalytics.filter((teamId) => !this.groupTypesMappingCache.get(teamId))

        if (teamsToLoad.length) {
            const result = await this.hub.postgres.query(
                PostgresUse.PERSONS_READ,
                `SELECT team_id, group_type, group_type_index FROM posthog_grouptypemapping WHERE team_id = ANY($1)`,
                [teamsToLoad],
                'fetchGroupTypes'
            )

            const groupedByTeam: Record<number, { type: string; index: number }[]> = result.rows.reduce((acc, row) => {
                if (!acc[row.team_id]) {
                    acc[row.team_id] = []
                }
                acc[row.team_id].push({ type: row.group_type, index: row.group_type_index })
                return acc
            }, {})

            // Save to cache
            Object.entries(groupedByTeam).forEach(([teamId, groupTypes]) => {
                this.groupTypesMappingCache.set(parseInt(teamId), groupTypes)
                groupTypes.forEach((row) => {
                    groupTypesMapping[`${teamId}:${row.type}`] = row.index
                })
            })
        }

        return groupTypesMapping
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

        return (
            await this.hub.postgres.query(
                PostgresUse.PERSONS_READ,
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
            // TODO: In the future move this kind of validation to Zod
            const validGroupsProperty: Record<string, string> = {}
            const groupsProperty = item.event.properties['$groups']

            if (typeof groupsProperty === 'object' && groupsProperty !== null) {
                Object.entries(groupsProperty).forEach(([groupType, groupKey]) => {
                    if (typeof groupType === 'string' && typeof groupKey === 'string') {
                        validGroupsProperty[groupType] = groupKey
                    }
                })
            }
            const groups: HogFunctionInvocationGlobals['groups'] = {}

            // Add the base group info without properties
            Object.entries(validGroupsProperty).forEach(([groupType, groupKey]) => {
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
        })
        const groupsFromDatabase = await this.fetchGroupProperties(Object.values(groupsByTeamTypeId))

        // Add the properties to all the groups
        groupsFromDatabase.forEach((row) => {
            const group = groupsByTeamTypeId[`${row.team_id}:${row.group_type_index}:${row.group_key}`]

            if (group) {
                group.properties = row.group_properties
            }
        })

        // Finally delete the teamId from the groupsByTeamTypeId
        Object.values(groupsByTeamTypeId).forEach((group) => {
            delete group.teamId
        })

        return items
    }
}
