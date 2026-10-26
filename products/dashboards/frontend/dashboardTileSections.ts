import { cloneLayout } from 'react-grid-layout'
import type { Compactor, Layout } from 'react-grid-layout'
import { moveElement } from 'react-grid-layout/core'

import { objectsEqual } from 'lib/utils/objects'
import { pluralize } from 'lib/utils/strings'
import { BREAKPOINT_COLUMN_COUNTS } from 'scenes/dashboard/dashboardUtils'

import type { DashboardLayoutSize, DashboardTile } from '~/types'

import type { DashboardGridCompactor } from './dashboardCustomization'
import type { DashboardTileGroupApi } from './generated/api.schemas'

export type DashboardSection =
    | { kind: 'tiles'; key: string; tiles: DashboardTile[] }
    | { kind: 'group'; key: string; groupKey: string; group: DashboardTileGroupApi; tiles: DashboardTile[] }

export type SectionLayouts = Partial<Record<DashboardLayoutSize, Layout>>

export interface TileGroupMoveOptions {
    targets: { sectionKey: string; label: string }[]
    canTakeOut: boolean
}

export function getTileGroupLabel(group: DashboardTileGroupApi, tileCount: number): string {
    return group.title || pluralize(tileCount, 'tile')
}

const TILE_GROUP_SECTION_KEY_PREFIX = 'group-'

export function isTileGroupSectionKey(sectionKey: string): boolean {
    return sectionKey.startsWith(TILE_GROUP_SECTION_KEY_PREFIX)
}

function tilesInLayoutOrder(tiles: DashboardTile[], layout: Layout | undefined): DashboardTile[] {
    const positions = new Map((layout ?? []).map((item) => [item.i, item]))
    const position = (tile: DashboardTile): [number, number] => {
        const item = positions.get(tile.id.toString())
        return item ? [item.y, item.x] : [Infinity, Infinity]
    }
    return [...tiles].sort((a, b) => {
        const [ay, ax] = position(a)
        const [by, bx] = position(b)
        return ay === by ? ax - bx : ay - by
    })
}

/** Splits tiles into full-width bands: each group starts where its top-left tile is, other tiles fill the gaps. */
export function getDashboardSections({
    tiles,
    layout,
    groups,
}: {
    tiles: DashboardTile[]
    layout: Layout | undefined
    groups: Record<string, DashboardTileGroupApi> | undefined
}): DashboardSection[] {
    const sections: DashboardSection[] = []
    const groupSections = new Map<string, DashboardSection>()

    for (const tile of tilesInLayoutOrder(tiles, layout)) {
        const groupKey = tile.group_key
        if (groupKey) {
            const existing = groupSections.get(groupKey)
            if (existing) {
                existing.tiles.push(tile)
                continue
            }
            const group = groups && Object.hasOwn(groups, groupKey) ? groups[groupKey] : {}
            const section: DashboardSection = {
                kind: 'group',
                key: `${TILE_GROUP_SECTION_KEY_PREFIX}${groupKey}`,
                groupKey,
                group,
                tiles: [tile],
            }
            groupSections.set(groupKey, section)
            sections.push(section)
            continue
        }
        const last = sections.at(-1)
        if (last?.kind === 'tiles') {
            last.tiles.push(tile)
        } else {
            // Named after the group above it, so the key holds when the band's own tiles reorder.
            const key = last ? `tiles-after-${last.groupKey}` : 'tiles-start'
            sections.push({ kind: 'tiles', key, tiles: [tile] })
        }
    }

    return sections
}

function moveToTop(layout: Layout): Layout {
    const top = Math.min(...layout.map((item) => item.y))
    return layout.map((item) => ({ ...item, y: item.y - top }))
}

// One column has nothing to place beside a tile, so a gap left by another band's tiles is only blank space.
function stackInOneColumn(layout: Layout): Layout {
    let y = 0
    return [...layout]
        .sort((a, b) => a.y - b.y || a.x - b.x)
        .map((item) => {
            const placed = { ...item, y }
            y += item.h
            return placed
        })
}

/**
 * A band's own layout, compacted the way its grid compacts it on mount.
 * Otherwise the grid closes the gaps left by other bands' tiles and reports a layout change nobody made.
 */
export function getSectionLayouts(
    layouts: SectionLayouts,
    tiles: DashboardTile[],
    compactor: Compactor
): SectionLayouts {
    const tileIds = new Set(tiles.map((tile) => tile.id.toString()))
    return Object.fromEntries(
        Object.entries(layouts).map(([size, layout]) => {
            const sectionLayout = (layout ?? []).filter((item) => tileIds.has(item.i))
            return [
                size,
                size === 'xs'
                    ? stackInOneColumn(sectionLayout)
                    : compactor.compact(moveToTop(sectionLayout), BREAKPOINT_COLUMN_COUNTS.sm),
            ]
        })
    )
}

/** Joins section layouts into one dashboard layout, each section under the one before it. */
export function stackSectionLayouts(sectionLayouts: Layout[]): Layout {
    let offset = 0
    return sectionLayouts.flatMap((sectionLayout) => {
        const stacked = moveToTop(sectionLayout).map((item) => ({ ...item, y: item.y + offset }))
        offset = Math.max(offset, ...stacked.map((item) => item.y + item.h))
        return stacked
    })
}

function geometry(layout: Layout): Pick<Layout[number], 'i' | 'x' | 'y' | 'w' | 'h'>[] {
    return [...layout].sort((a, b) => a.i.localeCompare(b.i)).map(({ i, x, y, w, h }) => ({ i, x, y, w, h }))
}

export function hasSectionLayoutChanged(before: Layout, after: Layout): boolean {
    return !objectsEqual(geometry(before), geometry(after))
}

/**
 * The dashboard layout after one band's grid reports its layout, or null when no tile in that band moved.
 * A grid also reports its layout when only its width crosses a breakpoint, and restacking the bands then would
 * move tiles that the person did not touch.
 */
export function getLayoutAfterSectionChange(sectionLayouts: Layout[], reportedLayout: Layout): Layout | null {
    const reportedTileIds = new Set(reportedLayout.map((item) => item.i))
    const sectionIndex = sectionLayouts.findIndex((layout) => layout.some((item) => reportedTileIds.has(item.i)))
    if (sectionIndex < 0 || !hasSectionLayoutChanged(sectionLayouts[sectionIndex], reportedLayout)) {
        return null
    }
    return stackSectionLayouts(
        sectionLayouts.map((layout, index) => (index === sectionIndex ? reportedLayout : layout))
    )
}

/** Group keys that start closed: the viewer's own choice wins over the dashboard's saved default. */
export function getCollapsedTileGroupKeys({
    tiles,
    groups,
    choices,
}: {
    tiles: DashboardTile[]
    groups: Record<string, DashboardTileGroupApi> | undefined
    choices: Record<string, boolean> | undefined
}): string[] {
    const groupKeys = new Set(tiles.map((tile) => tile.group_key).filter((groupKey): groupKey is string => !!groupKey))
    return [...groupKeys].filter((groupKey) => {
        if (choices && Object.hasOwn(choices, groupKey)) {
            return choices[groupKey]
        }
        return !!(groups && Object.hasOwn(groups, groupKey) && groups[groupKey].collapsed)
    })
}

export function getTileGroupMoveOptions(sections: DashboardSection[]): Record<number, TileGroupMoveOptions> {
    const targets = sections.flatMap((section) =>
        section.kind === 'group'
            ? [{ sectionKey: section.key, label: getTileGroupLabel(section.group, section.tiles.length) }]
            : []
    )
    return Object.fromEntries(
        sections.flatMap((section) => {
            const options: TileGroupMoveOptions = {
                targets: targets.filter((target) => target.sectionKey !== section.key),
                canTakeOut: section.kind === 'group',
            }
            return section.tiles.map((tile) => [tile.id, options])
        })
    )
}

export function getDropCell({
    tileRect,
    gridRect,
    cols,
    rowHeight,
    margin: [marginX, marginY],
    tileWidth,
}: {
    tileRect: { left: number; top: number }
    gridRect: { left: number; top: number; width: number }
    cols: number
    rowHeight: number
    margin: [number, number]
    tileWidth: number
}): { x: number; y: number } {
    const columnStep = (gridRect.width - marginX * (cols - 1)) / cols + marginX
    const x = Math.round((tileRect.left - gridRect.left) / columnStep)
    const y = Math.round((tileRect.top - gridRect.top) / (rowHeight + marginY))
    return { x: Math.min(Math.max(x, 0), cols - tileWidth), y: Math.max(y, 0) }
}

/**
 * The dashboard layout after a tile moves to the `target` section, or out of its group when `target` is null.
 * Without a drop cell the tile goes below the target's tiles and only its own layout item changes, so a save of
 * that one tile matches what the dashboard shows. A tile out of its group goes below every tile, which puts it in
 * the last band when that band has no group, and in a new band after the last group otherwise.
 */
export function getLayoutAfterTileMove({
    layout,
    sections,
    sectionLayouts,
    tileId,
    target,
    cell,
    compactor,
}: {
    layout: Layout
    sections: DashboardSection[]
    sectionLayouts: Layout[]
    tileId: number
    target: DashboardSection | null
    cell: { x: number; y: number } | null
    compactor: DashboardGridCompactor
}): Layout {
    const tileKey = tileId.toString()
    if (!cell || !target) {
        const targetTileIds = new Set(
            (target ? target.tiles : sections.flatMap((section) => section.tiles)).map((tile) => tile.id.toString())
        )
        targetTileIds.delete(tileKey)
        const bottom = Math.max(0, ...layout.filter((item) => targetTileIds.has(item.i)).map((item) => item.y + item.h))
        return layout.map((item) => (item.i === tileKey ? { ...item, y: bottom } : item))
    }

    const cols = BREAKPOINT_COLUMN_COUNTS.sm
    const sourceIndex = sections.findIndex((section) => section.tiles.some((tile) => tile.id === tileId))
    const targetIndex = sections.indexOf(target)
    const item = sectionLayouts[sourceIndex]?.find((layoutItem) => layoutItem.i === tileKey)
    if (!item) {
        return layout
    }
    const targetLayout = sectionLayouts[targetIndex] ?? []
    const bottom = Math.max(0, ...targetLayout.map((layoutItem) => layoutItem.y + layoutItem.h))
    // Enter at the bottom, then move to the drop cell the way a drag does, so the tile under the drop moves aside.
    const withTile = cloneLayout([...targetLayout, { ...item, y: bottom }])
    const moved = moveElement(
        withTile,
        withTile[withTile.length - 1],
        cell.x,
        cell.y,
        true,
        false,
        compactor.type,
        cols,
        compactor.allowOverlap
    )
    return stackSectionLayouts(
        sectionLayouts.map((sectionLayout, index) => {
            if (index === sourceIndex) {
                return compactor.compact(
                    sectionLayout.filter((layoutItem) => layoutItem.i !== tileKey),
                    cols
                )
            }
            if (index === targetIndex) {
                return compactor.compactInteraction(cols, tileKey, moved, moved, true)
            }
            return sectionLayout
        })
    )
}
