import { useValues } from 'kea'
import { useEffect, useState } from 'react'

import { groupDisplayId } from 'scenes/persons/GroupActorDisplay'
import { teamLogic } from 'scenes/teamLogic'

import { GroupTypeIndex } from '~/types'

import { cachedFindGroups } from './groupKeyTooltipLogic'

/**
 * Display names for filter values that are group keys, so a list of raw ids reads
 * as names. Only resolved keys are returned — callers fall back to the raw value,
 * which is also what a miss or a failed lookup leaves them with.
 */
export function useGroupKeyNames(groupTypeIndex: GroupTypeIndex | null, groupKeys: string[]): Record<string, string> {
    const { currentTeamId } = useValues(teamLogic)
    const [names, setNames] = useState<Record<string, string>>({})
    // Serialized so a caller passing a freshly built array doesn't re-resolve every render
    const serializedKeys = JSON.stringify(groupKeys)

    useEffect(() => {
        const keys: string[] = JSON.parse(serializedKeys)
        if (groupTypeIndex === null || !currentTeamId || keys.length === 0) {
            return
        }
        let stale = false
        void cachedFindGroups(currentTeamId, groupTypeIndex, keys).then((groups) => {
            if (stale) {
                return
            }
            const resolved: Record<string, string> = {}
            for (const [groupKey, group] of Object.entries(groups)) {
                if (group) {
                    resolved[groupKey] = groupDisplayId(group.group_key, group.group_properties)
                }
            }
            if (Object.keys(resolved).length > 0) {
                setNames((previous) => ({ ...previous, ...resolved }))
            }
        })
        return () => {
            stale = true
        }
    }, [currentTeamId, groupTypeIndex, serializedKeys])

    return names
}
