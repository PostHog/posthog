// Ticket groups for the tickets list: ordered, tag-based groups derived from
// ticket tags. Group order IS the priority order (first group highest): a
// ticket takes the highest-priority group with a matching tag, and tickets
// with no matching tag fall into the first group (they still need routing).
//
// Teams define their own groups in Settings → Support → Ticket groups
// (stored as conversations_settings.ticket_groups). Response-target ladders
// are one example use — the default below is only a starter example
// demonstrating the mechanic; every team's real groups (tag vocabulary,
// tiers, priorities) are their own. It MUST stay in lockstep with the
// backend copy in products/conversations/backend/ticket_groups.py.
//
// Matching is exact (no prefixes): a ticket tagged urgent_billing does NOT
// match a group on the tag urgent.

import type { TeamPublicType, TeamType } from '~/types'

export interface TicketGroup {
    label: string
    tags: string[]
}

export const DEFAULT_TICKET_GROUPS: TicketGroup[] = [
    { label: 'Triage', tags: ['needs_triage'] },
    { label: 'Urgent', tags: ['urgent'] },
    { label: 'VIP', tags: ['vip'] },
]

// tag → rank per group list, cached by list identity (the default groups and a
// team's groups from kea state are stable references, so each builds once).
const rankMaps = new WeakMap<TicketGroup[], Map<string, number>>()

function rankMap(groups: TicketGroup[]): Map<string, number> {
    let map = rankMaps.get(groups)
    if (!map) {
        map = new Map(groups.flatMap((group, rank) => group.tags.map((tag) => [tag, rank] as [string, number])))
        rankMaps.set(groups, map)
    }
    return map
}

/** Index into `groups` of the ticket's group — the best (lowest) rank across
 *  its tags, or the first group (0) when none match. */
export function ticketGroupRank(tags: string[] | undefined, groups: TicketGroup[] = DEFAULT_TICKET_GROUPS): number {
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

export function ticketGroupLabel(tags: string[] | undefined, groups: TicketGroup[] = DEFAULT_TICKET_GROUPS): string {
    return groups[ticketGroupRank(tags, groups)].label
}

/** The team's configured groups, or the default. The serializer validates
 *  writes, but the settings blob has other writers — treat anything malformed
 *  as unset. Returns the DEFAULT_TICKET_GROUPS reference itself when
 *  falling back, so memoization by identity keeps working. */
export function teamTicketGroups(team: TeamPublicType | TeamType | null): TicketGroup[] {
    const groups = team?.conversations_settings?.ticket_groups
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
    return DEFAULT_TICKET_GROUPS
}
