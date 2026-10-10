import { cloneLayout } from 'react-grid-layout'
import type { Compactor, Layout } from 'react-grid-layout'
import { correctBounds } from 'react-grid-layout/core'

import { BREAKPOINT_COLUMN_COUNTS } from 'scenes/dashboard/dashboardUtils'

import type { DashboardLayoutSize, DashboardTile } from '~/types'

interface GroupTitlesInput {
    tiles: DashboardTile[]
    layout: Layout | undefined
    activeBreakpoint: DashboardLayoutSize
    groupTitles: Record<string, string> | undefined
    compactor: Compactor
    widgetTilesShown: boolean
}

function getGroupTitle(groupTitles: Record<string, string>, groupKey: string): string | undefined {
    const title: unknown = Object.hasOwn(groupTitles, groupKey) ? groupTitles[groupKey] : undefined
    return typeof title === 'string' && title ? title : undefined
}

/** Repeats what the grid does before it paints: drop tiles it does not render, then clamp and compact. */
function getRenderedLayout(
    layout: Layout | undefined,
    breakpoint: DashboardLayoutSize,
    renderedTileIds: Set<string>,
    compactor: Compactor
): Layout {
    const cols = BREAKPOINT_COLUMN_COUNTS[breakpoint]
    const renderedLayout = cloneLayout((layout ?? []).filter((item) => renderedTileIds.has(item.i)))
    return compactor.compact(correctBounds(renderedLayout, { cols }), cols)
}

/** Maps each titled group to its top-left rendered tile, so the dashboard draws the group title once. */
export function getGroupTitlesByTileId({
    tiles,
    layout,
    activeBreakpoint,
    groupTitles,
    compactor,
    widgetTilesShown,
}: GroupTitlesInput): Record<number, string> {
    if (!groupTitles) {
        return {}
    }
    const renderedTiles = tiles.filter((tile) => !tile.widget || widgetTilesShown)
    const renderedLayout = getRenderedLayout(
        layout,
        activeBreakpoint,
        new Set(renderedTiles.map((tile) => tile.id.toString())),
        compactor
    )
    const positions = new Map(renderedLayout.map((item) => [item.i, item]))
    const firstTileByGroup = new Map<string, { tileId: number; title: string; y: number; x: number }>()

    for (const tile of renderedTiles) {
        if (!tile.group_key) {
            continue
        }
        const title = getGroupTitle(groupTitles, tile.group_key)
        if (!title) {
            continue
        }
        const position = positions.get(tile.id.toString())
        const y = position?.y ?? Infinity
        const x = position?.x ?? Infinity
        const current = firstTileByGroup.get(tile.group_key)
        if (!current || y < current.y || (y === current.y && x < current.x)) {
            firstTileByGroup.set(tile.group_key, { tileId: tile.id, title, y, x })
        }
    }

    return Object.fromEntries([...firstTileByGroup.values()].map(({ tileId, title }) => [tileId, title]))
}

export function hasTileDecorations({
    tiles,
    groupTitlesByTileId,
    widgetTilesShown,
}: {
    tiles: DashboardTile[]
    groupTitlesByTileId: Record<number, string>
    widgetTilesShown: boolean
}): boolean {
    return (
        Object.keys(groupTitlesByTileId).length > 0 ||
        tiles.some((tile) => !!tile.badge && (!tile.widget || widgetTilesShown))
    )
}
