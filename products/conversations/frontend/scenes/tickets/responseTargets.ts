// Response-target tiering for the tickets list, derived from ticket tags.
// Group order IS the priority order (first group highest): a ticket takes the
// highest-priority group with a matching tag, and tickets with no matching
// tag fall into the first group (they still need routing).
//
// Teams define their own ladder in Settings → Support → Response targets
// (stored as conversations_settings.response_target_groups). The default
// below is only a starter example demonstrating the mechanic — every team's
// real response targets (tag vocabulary, tiers, priorities) are their own.
// It MUST stay in lockstep with the backend copy in
// products/conversations/backend/response_targets.py.
//
// Matching is exact (no prefixes): a ticket tagged urgent_billing does NOT
// match a group on the tag urgent.

import type { TeamPublicType, TeamType } from '~/types'

export interface ResponseTargetGroup {
    label: string
    tags: string[]
}

export const DEFAULT_RESPONSE_TARGET_GROUPS: ResponseTargetGroup[] = [
    { label: 'Triage', tags: ['needs_triage'] },
    { label: 'Urgent', tags: ['urgent'] },
    { label: 'VIP', tags: ['vip'] },
]

// tag → rank per ladder, cached by ladder identity (the default ladder and a
// team's ladder from kea state are stable references, so each builds once).
const rankMaps = new WeakMap<ResponseTargetGroup[], Map<string, number>>()

function rankMap(groups: ResponseTargetGroup[]): Map<string, number> {
    let map = rankMaps.get(groups)
    if (!map) {
        map = new Map(groups.flatMap((group, rank) => group.tags.map((tag) => [tag, rank] as [string, number])))
        rankMaps.set(groups, map)
    }
    return map
}

/** Index into `groups` of the ticket's group — the best (lowest) rank across
 *  its tags, or the first group (0) when none match. */
export function responseTargetRank(
    tags: string[] | undefined,
    groups: ResponseTargetGroup[] = DEFAULT_RESPONSE_TARGET_GROUPS
): number {
    const ranks = rankMap(groups)
    let best = Number.POSITIVE_INFINITY
    for (const tag of tags ?? []) {
        const rank = ranks.get(tag)
        if (rank !== undefined && rank < best) {
            best = rank
        }
    }
    return best === Number.POSITIVE_INFINITY ? 0 : best
}

export function responseTargetLabel(
    tags: string[] | undefined,
    groups: ResponseTargetGroup[] = DEFAULT_RESPONSE_TARGET_GROUPS
): string {
    return groups[responseTargetRank(tags, groups)].label
}

/** The team's configured ladder, or the default. The serializer validates
 *  writes, but the settings blob has other writers — treat anything malformed
 *  as unset. Returns the DEFAULT_RESPONSE_TARGET_GROUPS reference itself when
 *  falling back, so memoization by identity keeps working. */
export function teamResponseTargetGroups(team: TeamPublicType | TeamType | null): ResponseTargetGroup[] {
    const groups = team?.conversations_settings?.response_target_groups
    if (
        Array.isArray(groups) &&
        groups.length > 0 &&
        groups.every(
            (group: any) =>
                group &&
                typeof group === 'object' &&
                typeof group.label === 'string' &&
                Array.isArray(group.tags) &&
                group.tags.every((tag: any) => typeof tag === 'string')
        ) &&
        // Duplicate labels would collide in the grouped view's per-label
        // headers, and a tag in two groups would rank with its FIRST group
        // server-side while the tag→rank map here keeps the LAST — treat
        // both as malformed too.
        new Set(groups.map((group: any) => group.label)).size === groups.length &&
        new Set(groups.flatMap((group: any) => group.tags)).size ===
            groups.reduce((sum: number, group: any) => sum + group.tags.length, 0)
    ) {
        return groups
    }
    return DEFAULT_RESPONSE_TARGET_GROUPS
}
