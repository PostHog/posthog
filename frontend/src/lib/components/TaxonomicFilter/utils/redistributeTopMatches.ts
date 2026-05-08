import { TaxonomicDefinitionTypes, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

export const DEFAULT_SLOTS_PER_GROUP = 5
export const MAX_TOP_MATCHES_PER_GROUP = 10
export const SKELETON_ROWS_PER_GROUP = 3

export const REDISTRIBUTION_PRIORITY_GROUPS: TaxonomicFilterGroupType[] = [
    TaxonomicFilterGroupType.CustomEvents,
    TaxonomicFilterGroupType.PageviewUrls,
    TaxonomicFilterGroupType.Screens,
]

export type TopMatchItem = TaxonomicDefinitionTypes & { group: TaxonomicFilterGroupType }

export function redistributeTopMatches(
    items: TopMatchItem[],
    activeGroupCount: number,
    groupTypeOrder: TaxonomicFilterGroupType[] = []
): TopMatchItem[] {
    if (items.length === 0) {
        return []
    }

    const byGroup = new Map<TaxonomicFilterGroupType, TopMatchItem[]>()
    for (const item of items) {
        if (!byGroup.has(item.group)) {
            byGroup.set(item.group, [])
        }
        byGroup.get(item.group)!.push(item)
    }

    const allocated = new Map<TaxonomicFilterGroupType, TopMatchItem[]>()
    let usedSlots = 0
    for (const [groupType, groupItems] of byGroup) {
        const take = Math.min(groupItems.length, DEFAULT_SLOTS_PER_GROUP)
        allocated.set(groupType, groupItems.slice(0, take))
        usedSlots += take
    }

    if (byGroup.size < 3) {
        const totalSlots = DEFAULT_SLOTS_PER_GROUP * activeGroupCount
        let surplus = totalSlots - usedSlots
        if (surplus > 0) {
            const presentGroups = Array.from(byGroup.keys())
            const priorityOrder = [
                ...REDISTRIBUTION_PRIORITY_GROUPS.filter((g) => presentGroups.includes(g)),
                ...presentGroups.filter((g) => !REDISTRIBUTION_PRIORITY_GROUPS.includes(g)),
            ]

            for (const groupType of priorityOrder) {
                if (surplus <= 0) {
                    break
                }
                const groupItems = byGroup.get(groupType)!
                const currentlyAllocated = allocated.get(groupType) || []
                const remaining = groupItems.slice(currentlyAllocated.length, MAX_TOP_MATCHES_PER_GROUP)
                const extra = Math.min(remaining.length, surplus)
                if (extra > 0) {
                    allocated.set(groupType, [...currentlyAllocated, ...remaining.slice(0, extra)])
                    surplus -= extra
                }
            }
        }
    }

    const displayOrder =
        groupTypeOrder.length > 0 ? groupTypeOrder.filter((g) => allocated.has(g)) : Array.from(allocated.keys())

    const result: TopMatchItem[] = []
    for (const groupType of displayOrder) {
        const groupItems = allocated.get(groupType)
        if (groupItems) {
            result.push(...groupItems)
        }
    }

    return result
}
