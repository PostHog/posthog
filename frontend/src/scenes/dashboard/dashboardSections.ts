import type { Layout, LayoutItem } from 'react-grid-layout'

import type { DashboardGroupApi } from '@posthog/products-dashboards/frontend/generated/api.schemas'

import type { DashboardLayoutSize, DashboardTile, QueryBasedInsightModel, TileLayout } from '~/types'

import { BREAKPOINT_COLUMN_COUNTS } from './dashboardUtils'
import { calculateLayouts } from './tileLayouts'

export const IMPLICIT_SECTION_KEY = 'implicit'
export const ORPHAN_SECTION_KEY = 'orphan'

export interface DashboardSection<T = QueryBasedInsightModel> {
    key: string
    group: DashboardGroupApi | null
    isNamed: boolean
    tiles: DashboardTile<T>[]
}

export interface DashboardSectionsLayout {
    layouts: Partial<Record<DashboardLayoutSize, Layout>>
    sectionByTileId: Record<number, string | null>
}

export function dashboardSectionHeaderId(groupId: string): string {
    return `dashboard-section-${groupId}`
}

export function isPersistedSectionKey(key: string): boolean {
    return key !== IMPLICIT_SECTION_KEY && key !== ORPHAN_SECTION_KEY
}

export function sectionDisplayName(group: DashboardGroupApi): string {
    const name = group.name?.trim()
    return name || 'Untitled section'
}

export function getFirstAvailableSectionRow(layout: Layout, x: number, y: number, w: number, h: number): number {
    let candidateY = y
    while (true) {
        const collisions = layout.filter(
            (item) => item.x < x + w && item.x + item.w > x && item.y < candidateY + h && item.y + item.h > candidateY
        )
        if (collisions.length === 0) {
            return candidateY
        }
        candidateY = Math.max(...collisions.map((item) => item.y + item.h))
    }
}

export function getDashboardSectionsPreview(
    sections: DashboardSection[],
    groupId: string | null,
    insertionPosition: number | null
): DashboardSection[] {
    if (!groupId || insertionPosition === null) {
        return sections
    }

    const sourcePosition = sections.findIndex((section) => section.group?.id === groupId)
    if (sourcePosition < 0) {
        return sections
    }

    const nextSections = [...sections]
    const [section] = nextSections.splice(sourcePosition, 1)
    const destinationPosition = insertionPosition > sourcePosition ? insertionPosition - 1 : insertionPosition
    nextSections.splice(Math.max(0, Math.min(destinationPosition, nextSections.length)), 0, section)
    return nextSections
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

    const sections = sortedGroups.map(
        (group): DashboardSection<T> => ({
            key: group.id,
            group,
            isNamed: !!group.name,
            tiles: tilesByGroup.get(group.id) ?? [],
        })
    )

    if (orphanTiles.length > 0) {
        sections.push({ key: ORPHAN_SECTION_KEY, group: null, isNamed: false, tiles: orphanTiles })
    }
    return sections
}

/**
 * Keeps section membership in the database while presenting sections as one continuous grid.
 * Header layouts are virtual: they never correspond to dashboard tile rows.
 */
export function buildDashboardSectionsLayout(sections: DashboardSection[]): DashboardSectionsLayout {
    const layouts: Partial<Record<DashboardLayoutSize, Layout>> = {}
    const sectionByTileId: Record<number, string | null> = {}

    for (const size of Object.keys(BREAKPOINT_COLUMN_COUNTS) as DashboardLayoutSize[]) {
        let nextY = 0
        const layout: LayoutItem[] = []

        for (const section of sections) {
            const sectionLayout = calculateLayouts(section.tiles)[size] ?? []
            const headerHeight = section.group ? 1 : 0
            if (section.group) {
                layout.push({
                    i: dashboardSectionHeaderId(section.group.id),
                    x: 0,
                    y: nextY,
                    w: BREAKPOINT_COLUMN_COUNTS[size],
                    h: 1,
                    isResizable: false,
                })
            }
            for (const tileLayout of sectionLayout) {
                const tileId = Number(tileLayout.i)
                sectionByTileId[tileId] = section.group?.id ?? null
                layout.push({ ...tileLayout, y: tileLayout.y + nextY + headerHeight })
            }
            nextY += headerHeight + Math.max(0, ...sectionLayout.map((item) => item.y + item.h))
        }
        layouts[size] = layout
    }

    return { layouts, sectionByTileId }
}

export function getTileLayoutsFromDashboardSectionsLayout(
    layout: Layout,
    groups: readonly DashboardGroupApi[]
): Record<number, { layouts: { sm: TileLayout }; parentGroupId: string | null }> {
    const headers = layout
        .filter((item) => item.i.startsWith('dashboard-section-'))
        .map((item) => ({ groupId: item.i.replace('dashboard-section-', ''), y: item.y }))
        .filter((header) => groups.some((group) => group.id === header.groupId))
        .sort((a, b) => a.y - b.y)

    return Object.fromEntries(
        layout
            .filter((item) => !item.i.startsWith('dashboard-section-'))
            .map((item) => {
                const header = [...headers].reverse().find((candidate) => candidate.y < item.y)
                const localY = item.y - (header ? header.y + 1 : 0)
                return [
                    Number(item.i),
                    { layouts: { sm: { ...item, y: Math.max(0, localY) } }, parentGroupId: header?.groupId ?? null },
                ]
            })
    )
}
