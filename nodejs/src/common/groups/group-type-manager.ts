import { DateTime } from 'luxon'
import { Counter } from 'prom-client'

import { GroupRepository } from '~/common/groups/repositories/group-repository.interface'
import { timeoutGuard } from '~/common/utils/db/utils'
import { LazyLoader, LoaderRetryOptions } from '~/common/utils/lazy-loader'
import { captureTeamEvent } from '~/common/utils/posthog'
import { TeamManager } from '~/common/utils/team-manager'
import {
    GroupTypeIndex,
    GroupTypeMappingRow,
    GroupTypeToColumnIndex,
    GroupTypesByProjectId,
    ProjectId,
    Team,
    TeamId,
} from '~/types'

/** How many unique group types to allow per team */
export const MAX_GROUP_TYPES_PER_TEAM = 5

// The masking this heals is silent, so a stale floor reads as missing data rather than a bug.
// This is the only signal that historical events are still landing behind their group type mapping.
const groupTypeCreatedAtLoweredCounter = new Counter({
    name: 'group_type_created_at_lowered_total',
    help: 'Group type mappings whose created_at floor was lowered by an older event',
})

type CachedGroupTypes = Record<string, GroupTypeMappingRow>

export interface GroupTypeManagerOptions {
    /** Retry transient group-type-load failures (e.g. a Postgres pooler blip) instead of letting them propagate. */
    loaderRetry?: LoaderRetryOptions
}

function toColumnIndex(groupTypes: CachedGroupTypes): GroupTypeToColumnIndex {
    const columnIndex: GroupTypeToColumnIndex = {}
    for (const [groupType, row] of Object.entries(groupTypes)) {
        columnIndex[groupType] = row.group_type_index
    }
    return columnIndex
}

/**
 * Truncating the floor to the day bounds how often an import rewrites it: an import that pages
 * newest-first lowers the floor on every event otherwise, since each one is a new minimum. A
 * day-start floor can only unmask more events than the exact timestamp would, never fewer.
 */
function floorFor(eventTimestamp: DateTime): DateTime {
    return eventTimestamp.startOf('day')
}

export class GroupTypeManager {
    private loader: LazyLoader<CachedGroupTypes>

    constructor(
        private groupRepository: GroupRepository,
        private teamManager: TeamManager,
        options?: GroupTypeManagerOptions
    ) {
        this.loader = new LazyLoader({
            name: 'GroupTypeManager',
            refreshAgeMs: 30_000, // 30 seconds
            refreshJitterMs: 0,
            loaderRetry: options?.loaderRetry,
            loader: async (projectIds: string[]) => {
                const response: Record<string, CachedGroupTypes> = {}
                const timeout = timeoutGuard(`Still running "fetchGroupTypes". Timeout warning after 30 sec!`)
                try {
                    const projectIdNumbers = projectIds.map((id) => parseInt(id) as ProjectId)
                    const groupTypesByProject = await this.groupRepository.fetchGroupTypesByProjectIds(
                        projectIdNumbers,
                        'ingestion/group-type-resolution'
                    )

                    for (const [projectIdStr, groupTypes] of Object.entries(groupTypesByProject)) {
                        const groupTypeMapping: CachedGroupTypes = {}
                        for (const groupType of groupTypes) {
                            groupTypeMapping[groupType.group_type] = groupType
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
        return toColumnIndex(await this.cachedGroupTypes(projectId))
    }

    private async cachedGroupTypes(projectId: ProjectId): Promise<CachedGroupTypes> {
        return (await this.loader.get(projectId.toString())) ?? {}
    }

    /** Resolve a group type to its column index from the cached mapping only — never creates a mapping. */
    public async lookupGroupTypeIndex(projectId: ProjectId, groupType: string): Promise<GroupTypeIndex | null> {
        return (await this.lookupCachedGroupType(projectId, groupType))?.group_type_index ?? null
    }

    /**
     * Own-property + type guarded: the mapping is a plain object, so an attacker-supplied name
     * like "__proto__" or "constructor" would otherwise resolve to an inherited non-numeric
     * value and poison downstream SQL parameters.
     */
    private async lookupCachedGroupType(projectId: ProjectId, groupType: string): Promise<GroupTypeMappingRow | null> {
        const groupTypes = await this.cachedGroupTypes(projectId)
        const cached = Object.hasOwn(groupTypes, groupType) ? groupTypes[groupType] : undefined
        return typeof cached?.group_type_index === 'number' ? cached : null
    }

    public async fetchGroupTypeIndex(
        teamId: TeamId,
        projectId: ProjectId,
        groupType: string,
        eventTimestamp: DateTime
    ): Promise<GroupTypeIndex | null> {
        const existing = await this.lookupCachedGroupType(projectId, groupType)
        if (existing !== null) {
            await this.lowerCreatedAtFloor(projectId, groupType, existing, eventTimestamp)
            return existing.group_type_index
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

            if (isInsert) {
                // TODO: Is the `group type ingested` event being valuable? If not, we can remove
                // `captureGroupTypeInsert()`. If yes, we should move this capture to use the project instead of team
                await this.captureGroupTypeInsert(teamId, groupType, groupTypeIndex)
            } else {
                // Another writer created the mapping first, so our own event timestamp never reached it.
                await this.lowerStoredCreatedAt(projectId, groupType, floorFor(eventTimestamp))
            }
        }
        return groupTypeIndex
    }

    /**
     * Keep the mapping's `created_at` at or below the oldest event seen carrying the group. Without
     * this a historical import inherits whatever date first registered the type — often a small trial
     * import at wall-clock now — and HogQL reads every older event as ungrouped.
     */
    private async lowerCreatedAtFloor(
        projectId: ProjectId,
        groupType: string,
        cached: GroupTypeMappingRow,
        eventTimestamp: DateTime
    ): Promise<void> {
        // A null floor is not ours to move: it masks nothing, so lowering it would start masking a
        // project that was never affected.
        const floor = floorFor(eventTimestamp)
        if (!cached.created_at || floor >= cached.created_at) {
            return
        }

        await this.lowerStoredCreatedAt(projectId, groupType, floor)
        // Only suppress the rest of the import once the write has landed, so a failed write is retried
        // rather than hidden behind a cache that claims a floor Postgres does not have.
        cached.created_at = floor
    }

    private async lowerStoredCreatedAt(projectId: ProjectId, groupType: string, floor: DateTime): Promise<void> {
        if (await this.groupRepository.lowerGroupTypeCreatedAt(projectId, groupType, floor)) {
            groupTypeCreatedAtLoweredCounter.inc()
        }
    }

    public async fetchGroupTypesForProjects(projectIds: ProjectId[] | Set<ProjectId>): Promise<GroupTypesByProjectId> {
        const results = await this.loader.getMany(Array.from(projectIds).map((id) => id.toString()))

        return Object.fromEntries(
            Object.entries(results).map(([projectId, groupTypes]) => [projectId, toColumnIndex(groupTypes ?? {})])
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
