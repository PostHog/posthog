import { cloneLayout } from 'react-grid-layout'
import type { Layout } from 'react-grid-layout'
import { moveElement } from 'react-grid-layout/core'

import { pluralize } from 'lib/utils/strings'

import type { DashboardLayoutSize, DashboardTile } from '~/types'

import type { DashboardGridCompactor } from './dashboardCustomization'
import type { DashboardTileGroupApi } from './generated/api.schemas'

export type DashboardSection =
    | { kind: 'tiles'; key: string; tiles: DashboardTile[] }
    | { kind: 'group'; key: string; groupKey: string; group: DashboardTileGroupApi; tiles: DashboardTile[] }

type SectionLayouts = Partial<Record<DashboardLayoutSize, Layout>>

/** Where a tile's menu can move it on its own dashboard. */
export interface TileGroupMoveOptions {
    groups: { groupKey: string; label: string }[]
    inGroup: boolean
}

/** The name a group's band header shows. */
export function getTileGroupLabel(group: DashboardTileGroupApi, tileCount: number): string {
    return group.title || pluralize(tileCount, 'tile')
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
                key: `group-${groupKey}`,
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

/** For each tile, the other groups of its dashboard, and whether it is in a group it can leave. */
export function getTileGroupMoveOptions(sections: DashboardSection[]): Record<number, TileGroupMoveOptions> {
    const groups = sections.flatMap((section) =>
        section.kind === 'group'
            ? [{ groupKey: section.groupKey, label: getTileGroupLabel(section.group, section.tiles.length) }]
            : []
    )
    return Object.fromEntries(
        sections.flatMap((section) => {
            const currentGroupKey = section.kind === 'group' ? section.groupKey : null
            const options: TileGroupMoveOptions = {
                groups: groups.filter((group) => group.groupKey !== currentGroupKey),
                inGroup: currentGroupKey !== null,
            }
            return section.tiles.map((tile) => [tile.id, options])
        })
    )
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

export function getSectionLayouts(layouts: SectionLayouts, tiles: DashboardTile[]): SectionLayouts {
    const tileIds = new Set(tiles.map((tile) => tile.id.toString()))
    return Object.fromEntries(
        Object.entries(layouts).map(([size, layout]) => {
            const sectionLayout = (layout ?? []).filter((item) => tileIds.has(item.i))
            return [size, size === 'xs' ? stackInOneColumn(sectionLayout) : moveToTop(sectionLayout)]
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

export function hasSectionLayoutChanged(before: Layout, after: Layout): boolean {
    const beforeById = new Map(before.map((item) => [item.i, item]))
    return (
        before.length !== after.length ||
        after.some((item) => {
            const previous = beforeById.get(item.i)
            return (
                !previous ||
                previous.x !== item.x ||
                previous.y !== item.y ||
                previous.w !== item.w ||
                previous.h !== item.h
            )
        })
    )
}

/**
 * The dashboard layout after one band's grid reports its layout, or null when no tile in that band moved.
 * A grid also reports its layout when only its width crosses a breakpoint, and restacking the bands then would
 * move tiles that the person did not touch.
 */
export function getLayoutAfterSectionChange(
    sectionLayouts: Layout[],
    sectionIndex: number,
    reportedLayout: Layout
): Layout | null {
    if (!hasSectionLayoutChanged(sectionLayouts[sectionIndex] ?? [], reportedLayout)) {
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

/** The grid cell nearest to a dragged tile's top-left corner, kept so the whole tile fits in the grid. */
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
 * Moves a tile from its section into another one, or into a new ungrouped section when `targetIndex` is past the
 * last section. Without a drop cell the tile goes to the bottom of the target.
 */
export function moveTileToSection({
    sections,
    sectionLayouts,
    tileId,
    targetIndex,
    cell,
    compactor,
    cols,
}: {
    sections: DashboardSection[]
    sectionLayouts: Layout[]
    tileId: number
    targetIndex: number
    cell: { x: number; y: number } | null
    compactor: DashboardGridCompactor
    cols: number
}): { layout: Layout; groupKey: string | null } {
    const tileKey = tileId.toString()
    const sourceIndex = sections.findIndex((section) => section.tiles.some((tile) => tile.id === tileId))
    const item = sectionLayouts[sourceIndex]?.find((layoutItem) => layoutItem.i === tileKey)
    if (!item) {
        return { layout: stackSectionLayouts(sectionLayouts), groupKey: null }
    }

    const targetLayout = sectionLayouts[targetIndex] ?? []
    const bottom = Math.max(0, ...targetLayout.map((layoutItem) => layoutItem.y + layoutItem.h))
    // Enter at the bottom, then move to the drop cell the way a drag does, so the tile under the drop moves aside.
    const withTile = cloneLayout([...targetLayout, { ...item, y: bottom }])
    const entered = withTile[withTile.length - 1]
    const moved = cell
        ? moveElement(withTile, entered, cell.x, cell.y, true, false, compactor.type, cols, compactor.allowOverlap)
        : withTile
    const layouts = [...sectionLayouts, ...(targetIndex >= sectionLayouts.length ? [[]] : [])].map((layout, index) => {
        if (index === sourceIndex) {
            return compactor.compact(
                layout.filter((layoutItem) => layoutItem.i !== tileKey),
                cols
            )
        }
        if (index === targetIndex) {
            return compactor.compactInteraction(cols, tileKey, moved, moved, true)
        }
        return layout
    })
    const target = sections[targetIndex]
    return {
        layout: stackSectionLayouts(layouts),
        groupKey: target?.kind === 'group' ? target.groupKey : null,
    }
}
