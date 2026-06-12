import { afterMount, connect, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import { Group, GroupTypeIndex } from '~/types'

import { findGroups } from './groupKeySelectLogic'
import type { groupKeyTooltipLogicType } from './groupKeyTooltipLogicType'

export interface GroupKeyTooltipLogicProps {
    groupTypeIndex: GroupTypeIndex
    groupKeys: string[]
}

// Resolved lookups survive tooltip close/reopen so a given key is only ever
// fetched once. A null entry records a key we looked up but didn't find, so we
// don't keep retrying misses (e.g. a pasted UUID that isn't a real group).
const groupLookupCache = new Map<string, Group | null>()

const cacheKey = (teamId: number, groupTypeIndex: GroupTypeIndex, groupKey: string): string =>
    `${teamId}:${groupTypeIndex}:${groupKey}`

// Exposed for tests — the cache is a module singleton, so it must be reset
// between cases to keep them independent.
export function clearGroupLookupCache(): void {
    groupLookupCache.clear()
}

async function cachedFindGroups(
    teamId: number | null,
    groupTypeIndex: GroupTypeIndex,
    groupKeys: string[]
): Promise<Record<string, Group>> {
    if (!teamId) {
        return {}
    }
    const resolved: Record<string, Group> = {}
    const uncachedKeys: string[] = []
    for (const groupKey of groupKeys) {
        const k = cacheKey(teamId, groupTypeIndex, groupKey)
        if (groupLookupCache.has(k)) {
            const cached = groupLookupCache.get(k)
            if (cached) {
                resolved[groupKey] = cached
            }
        } else {
            uncachedKeys.push(groupKey)
        }
    }
    if (uncachedKeys.length > 0) {
        const found = await findGroups(teamId, groupTypeIndex, uncachedKeys)
        for (const groupKey of uncachedKeys) {
            // Only cache a definitive result (a group, or null for a 404 miss).
            // Transient failures are absent from `found`, so we leave them
            // uncached and the next hover retries them.
            if (groupKey in found) {
                const group = found[groupKey]
                groupLookupCache.set(cacheKey(teamId, groupTypeIndex, groupKey), group)
                if (group) {
                    resolved[groupKey] = group
                }
            }
        }
    }
    return resolved
}

export const groupKeyTooltipLogic = kea<groupKeyTooltipLogicType>([
    props({} as GroupKeyTooltipLogicProps),
    key((props) => `${props.groupTypeIndex}-${JSON.stringify([...props.groupKeys].sort())}`),
    path((key) => ['lib', 'components', 'PropertyFilters', 'components', 'groupKeyTooltipLogic', key]),
    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
    })),
    loaders(({ values, props }) => ({
        groups: [
            {} as Record<string, Group>,
            {
                loadGroups: async () => cachedFindGroups(values.currentTeamId, props.groupTypeIndex, props.groupKeys),
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadGroups()
    }),
])
