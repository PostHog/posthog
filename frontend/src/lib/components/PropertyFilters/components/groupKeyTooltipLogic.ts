import { afterMount, connect, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import { Group, GroupTypeIndex } from '~/types'

import { findGroups } from './groupKeySelectLogic'
import type { groupKeyTooltipLogicType } from './groupKeyTooltipLogicType'

export interface GroupKeyTooltipLogicProps {
    groupTypeIndex: GroupTypeIndex
    groupKey: string
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

async function cachedFindGroup(
    teamId: number | null,
    groupTypeIndex: GroupTypeIndex,
    groupKey: string
): Promise<Group | null> {
    if (!teamId) {
        return null
    }
    const k = cacheKey(teamId, groupTypeIndex, groupKey)
    if (groupLookupCache.has(k)) {
        return groupLookupCache.get(k) ?? null
    }
    const found = await findGroups(teamId, groupTypeIndex, [groupKey])
    // Only cache a definitive result (a group, or null for a 404 miss).
    // Transient failures are absent from `found`, so we leave them uncached
    // and the next hover retries them.
    if (groupKey in found) {
        const group = found[groupKey]
        groupLookupCache.set(k, group)
        return group
    }
    return null
}

export const groupKeyTooltipLogic = kea<groupKeyTooltipLogicType>([
    props({} as GroupKeyTooltipLogicProps),
    key((props) => `${props.groupTypeIndex}-${props.groupKey}`),
    path((key) => ['lib', 'components', 'PropertyFilters', 'components', 'groupKeyTooltipLogic', key]),
    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
    })),
    loaders(({ values, props }) => ({
        group: [
            null as Group | null,
            {
                loadGroup: async () => cachedFindGroup(values.currentTeamId, props.groupTypeIndex, props.groupKey),
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadGroup()
    }),
])
