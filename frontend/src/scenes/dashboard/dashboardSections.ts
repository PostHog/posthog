import type { DashboardGroupApi } from '@posthog/products-dashboards/frontend/generated/api.schemas'

import type { DashboardTile, QueryBasedInsightModel } from '~/types'

export const IMPLICIT_SECTION_KEY = 'implicit'
export const ORPHAN_SECTION_KEY = 'orphan'

export interface DashboardSection<T = QueryBasedInsightModel> {
    key: string
    group: DashboardGroupApi | null
    isNamed: boolean
    tiles: DashboardTile<T>[]
}

export function isPersistedSectionKey(key: string): boolean {
    return key !== IMPLICIT_SECTION_KEY && key !== ORPHAN_SECTION_KEY
}

export function sectionDisplayName(group: DashboardGroupApi): string {
    const name = group.name?.trim()
    return name || 'Untitled section'
}

export function partitionDashboardSections<T = QueryBasedInsightModel>(
    tiles: DashboardTile<T>[],
    groups: readonly DashboardGroupApi[] | undefined
): DashboardSection<T>[] {
    const sortedGroups = [...(groups ?? [])].sort(
        (firstGroup, secondGroup) =>
            firstGroup.position - secondGroup.position || firstGroup.created_at.localeCompare(secondGroup.created_at)
    )
    if (sortedGroups.length === 0) {
        return [{ key: IMPLICIT_SECTION_KEY, group: null, isNamed: false, tiles }]
    }

    const tilesByGroup = new Map<string, DashboardTile<T>[]>()
    const orphanTiles: DashboardTile<T>[] = []
    const groupIds = new Set(sortedGroups.map((group) => group.id))
    for (const tile of tiles) {
        if (tile.parent_group_id && groupIds.has(tile.parent_group_id)) {
            const groupTiles = tilesByGroup.get(tile.parent_group_id) ?? []
            groupTiles.push(tile)
            tilesByGroup.set(tile.parent_group_id, groupTiles)
        } else {
            orphanTiles.push(tile)
        }
    }

    const sections = sortedGroups
        .map(
            (group): DashboardSection<T> => ({
                key: group.id,
                group,
                isNamed: !!group.name,
                tiles: tilesByGroup.get(group.id) ?? [],
            })
        )
        .filter((section) => section.isNamed || section.tiles.length > 0)

    if (orphanTiles.length > 0) {
        sections.push({ key: ORPHAN_SECTION_KEY, group: null, isNamed: false, tiles: orphanTiles })
    }
    return sections
}
