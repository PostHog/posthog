import { sanitizeString } from '~/utils/db/utils'
import { LazyLoader } from '~/utils/lazy-loader'
import { logger } from '~/utils/logger'
import { TeamManager } from '~/utils/team-manager'
import { GroupRepository } from '~/worker/ingestion/groups/repositories/group-repository.interface'

import { GroupTypeIndex, Team } from '../../../types'
import { GroupType, HogFunctionInvocationGlobals } from '../../types'

export type GroupsMap = Record<string, GroupType>
export type GroupsCache = Record<Team['id'], GroupsMap>

// groupType -> groupTypeIndex for a single team
type GroupTypeMapping = Record<string, number>

const toGroupPropertiesKey = (teamId: number, groupTypeIndex: number, groupKey: string): string =>
    `${teamId}:${groupTypeIndex}:${groupKey}`

const fromGroupPropertiesKey = (key: string): { teamId: number; groupTypeIndex: number; groupKey: string } => {
    const [teamIdStr, groupTypeIndexStr, ...groupKeyParts] = key.split(':')
    return {
        teamId: parseInt(teamIdStr),
        groupTypeIndex: parseInt(groupTypeIndexStr),
        groupKey: groupKeyParts.join(':'),
    }
}

export class GroupsManagerServiceV2 {
    private groupTypesLoader: LazyLoader<GroupTypeMapping>
    private groupPropertiesLoader: LazyLoader<Record<string, any>>

    constructor(
        private teamManager: TeamManager,
        private groupRepository: GroupRepository
    ) {
        this.groupTypesLoader = new LazyLoader({
            name: 'groups_manager_types',
            refreshAgeMs: 10 * 60 * 1000, // 10 minutes - group types rarely change
            loader: async (teamIds) => this.fetchGroupTypes(teamIds),
        })

        this.groupPropertiesLoader = new LazyLoader({
            name: 'groups_manager_properties',
            refreshAgeMs: 60 * 1000, // 1 minute
            loader: async (keys) => this.fetchGroupPropertiesBatch(keys),
        })
    }

    public clear(): void {
        this.groupTypesLoader.clear()
        this.groupPropertiesLoader.clear()
    }

    /**
     * Loads groups for a given team and event, returning the groups record.
     * Can be used directly when a full globals object isn't available (e.g. hogflow worker).
     */
    public async getGroupsForEvent(
        teamId: number,
        eventProperties: Record<string, any>,
        projectUrl: string
    ): Promise<Record<string, GroupType>> {
        // Early return - if there are no $groups on the event then we don't need to do anything
        const groupsProperty = eventProperties['$groups']
        if (typeof groupsProperty !== 'object' || groupsProperty === null || Object.keys(groupsProperty).length === 0) {
            return {}
        }

        const typeMapping = await this.groupTypesLoader.get(String(teamId))
        if (!typeMapping) {
            logger.warn('No group types found for team', { teamId })
            return {}
        }

        const groups: Record<string, GroupType> = {}
        const entries: { compositeKey: string; sanitizedType: string; sanitizedKey: string; groupIndex: number }[] = []

        for (const [groupType, groupKey] of Object.entries(groupsProperty)) {
            if (typeof groupType !== 'string' || typeof groupKey !== 'string') {
                continue
            }

            const sanitizedType = sanitizeString(groupType)
            const sanitizedKey = sanitizeString(groupKey)
            const groupIndex = typeMapping[sanitizedType]

            if (typeof groupIndex !== 'number') {
                continue
            }

            entries.push({
                compositeKey: toGroupPropertiesKey(teamId, groupIndex, sanitizedKey),
                sanitizedType,
                sanitizedKey,
                groupIndex,
            })
        }

        if (entries.length === 0) {
            return {}
        }

        const propertiesMap = await this.groupPropertiesLoader.getMany(entries.map((e) => e.compositeKey))

        for (const { compositeKey, sanitizedType, sanitizedKey, groupIndex } of entries) {
            groups[sanitizedType] = {
                id: sanitizedKey,
                index: groupIndex,
                type: sanitizedType,
                url: `${projectUrl}/groups/${groupIndex}/${encodeURIComponent(sanitizedKey)}`,
                properties: propertiesMap[compositeKey] ?? {},
            }
        }

        return groups
    }

    /**
     * Enriches a single globals context with group type info and properties.
     *
     * Designed to be called per-item. When multiple calls happen concurrently
     * (e.g. via Promise.all), the LazyLoader batches the underlying DB queries.
     */
    public async addGroupsToGlobals(globals: HogFunctionInvocationGlobals): Promise<void> {
        if (globals.groups) {
            return
        }

        globals.groups = await this.getGroupsForEvent(globals.project.id, globals.event.properties, globals.project.url)
    }

    public async addGroupsToGlobalsList(globalsList: HogFunctionInvocationGlobals[]): Promise<void> {
        await Promise.all(globalsList.map((globals) => this.addGroupsToGlobals(globals)))
    }

    private async fetchGroupTypes(teamIdStrs: string[]): Promise<Record<string, GroupTypeMapping | null | undefined>> {
        const result: Record<string, GroupTypeMapping | null | undefined> = {}
        const teamsToLoad: number[] = []

        for (const teamIdStr of teamIdStrs) {
            const teamId = parseInt(teamIdStr)
            if (await this.teamManager.hasAvailableFeature(teamId, 'group_analytics')) {
                teamsToLoad.push(teamId)
            } else {
                result[teamIdStr] = null
            }
        }

        if (teamsToLoad.length > 0) {
            const repoResult = await this.groupRepository.fetchGroupTypesByTeamIds(teamsToLoad)
            for (const teamId of teamsToLoad) {
                const groupTypes = repoResult[String(teamId)] ?? []
                const mapping: GroupTypeMapping = {}
                for (const gt of groupTypes) {
                    mapping[gt.group_type] = gt.group_type_index
                }
                result[String(teamId)] = mapping
            }
        }

        return result
    }

    private async fetchGroupPropertiesBatch(
        keys: string[]
    ): Promise<Record<string, Record<string, any> | null | undefined>> {
        const parsed = keys.map(fromGroupPropertiesKey)

        const teamIds = parsed.map((p) => p.teamId)
        const groupIndexes = parsed.map((p) => p.groupTypeIndex) as GroupTypeIndex[]
        const groupKeys = parsed.map((p) => p.groupKey)

        const rows = await this.groupRepository.fetchGroupsByKeys(teamIds, groupIndexes, groupKeys)

        const result: Record<string, Record<string, any> | null | undefined> = {}
        for (const row of rows) {
            const key = toGroupPropertiesKey(row.team_id, row.group_type_index, row.group_key)
            result[key] = row.group_properties
        }

        return result
    }
}
