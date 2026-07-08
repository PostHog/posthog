import { Layout } from 'react-grid-layout'

import {
    DASHBOARD_WIDGET_CATALOG,
    getDashboardWidgetCatalogEntry,
    type DashboardWidgetCatalogEntry,
} from '@posthog/products-dashboards/frontend/widget_types/catalog'

import { BREAKPOINT_COLUMN_COUNTS } from 'scenes/dashboard/dashboardUtils'

import { getQueryBasedInsightModel } from '~/queries/nodes/InsightViz/utils'
import { isFunnelsQuery, isPathsQuery, isRetentionQuery, isTrendsQuery } from '~/queries/utils'
import { ChartDisplayType, DashboardLayoutSize, DashboardTile, QueryBasedInsightModel } from '~/types'

export interface TileLayout {
    x: number
    y: number
    w: number
    h: number
}

const MIN_TILE_HEIGHT_ROWS = 2
const MIN_TEXT_TILE_HEIGHT_ROWS = 1
const MIN_WIDGET_TILE_WIDTH_COLS = 3
const MIN_WIDGET_TILE_HEIGHT_ROWS = 4

/** Fallback tile dimensions (half-width, standard height) when a tile has no known layout yet. */
export const DEFAULT_INSERTED_TILE_SIZE = { w: 6, h: 5 } as const

export const DEFAULT_TEXT_TILE_SIZE = { w: 2, h: 2 } as const

type WidgetCatalogLayout = DashboardWidgetCatalogEntry['defaultLayout']

/**
 * Widget tile sizing from `DASHBOARD_WIDGET_CATALOG[].defaultLayout` (w, h, minW, minH).
 * Returns undefined when `widget_type` is missing or unknown; callers use scene fallbacks
 * (default size 6×5, mins `MIN_WIDGET_TILE_WIDTH_COLS` / `MIN_WIDGET_TILE_HEIGHT_ROWS`).
 */
function getWidgetCatalogLayout(widgetType: string | undefined): WidgetCatalogLayout | undefined {
    if (!widgetType || !(widgetType in DASHBOARD_WIDGET_CATALOG)) {
        return undefined
    }
    return getDashboardWidgetCatalogEntry(widgetType).defaultLayout
}

function getTileMinDimensions({
    isTextTile,
    isButtonTile,
    isWidgetTile,
    widgetCatalogLayout,
}: {
    isTextTile: boolean
    isButtonTile: boolean
    isWidgetTile: boolean
    widgetCatalogLayout: WidgetCatalogLayout | undefined
}): { minW: number; minH: number } {
    if (isTextTile || isButtonTile) {
        return { minW: 1, minH: MIN_TEXT_TILE_HEIGHT_ROWS }
    }
    if (isWidgetTile) {
        return {
            minW: widgetCatalogLayout?.minW ?? MIN_WIDGET_TILE_WIDTH_COLS,
            minH: widgetCatalogLayout?.minH ?? MIN_WIDGET_TILE_HEIGHT_ROWS,
        }
    }
    return { minW: 2, minH: MIN_TILE_HEIGHT_ROWS }
}

export interface DuplicateLayoutResult {
    duplicateLayouts: { sm?: TileLayout }
    tilesToUpdate: Array<{ id: number; layouts: { sm?: TileLayout } }>
}

export function calculateDuplicateLayout(
    currentLayouts: Partial<Record<DashboardLayoutSize, Layout>> | null,
    tileId: number
): DuplicateLayoutResult {
    const result: DuplicateLayoutResult = { duplicateLayouts: {}, tilesToUpdate: [] }

    const originalSmLayout = currentLayouts?.sm?.find((l) => l.i === `${tileId}`)

    if (!originalSmLayout) {
        return result
    }

    const { x, y, w, h } = originalSmLayout
    const columnCount = BREAKPOINT_COLUMN_COUNTS.sm

    // place the tile on the right if there's space
    if (canPlaceToRight(currentLayouts?.sm || [], tileId, x, y, w, h, columnCount)) {
        result.duplicateLayouts = {
            sm: { x: x + w, y, w, h },
        }
        return result
    }

    // otherwise, place it below
    const insertY = y + h
    result.duplicateLayouts = {
        sm: { x, y: insertY, w, h },
    }

    // shift down any tiles that would overlap with the new placement
    for (const smLayout of currentLayouts?.sm || []) {
        // ignore the duplicated tile and tiles above the insertion point
        if (smLayout.i === `${tileId}` || smLayout.y < insertY) {
            continue
        }

        result.tilesToUpdate.push({
            id: Number(smLayout.i),
            layouts: {
                sm: { x: smLayout.x, y: smLayout.y + h, w: smLayout.w, h: smLayout.h },
            },
        })
    }

    return result
}

export interface InsertionLayoutResult {
    newTileLayout: { sm: TileLayout }
    tilesToUpdate: Array<{ id: number; layouts: { sm?: TileLayout } }>
}

/**
 * Layout for inserting a tile at a given grid slot: the new tile lands at (`targetX`, `targetY`) and
 * only tiles sharing its column span (those horizontally overlapping the new tile) that sit at or
 * below `targetY` are pushed down by `h` rows. Tiles in other columns stay put, so inserting into the
 * right column doesn't shove the left one. Mirrors `calculateDuplicateLayout`'s `tilesToUpdate` shape
 * so persistence is shared.
 */
export function calculateInsertionLayout(
    currentSmLayout: Layout | undefined,
    newTileId: number,
    targetY: number,
    targetX: number,
    w: number,
    h: number
): InsertionLayoutResult {
    const result: InsertionLayoutResult = {
        newTileLayout: { sm: { x: targetX, y: targetY, w, h } },
        tilesToUpdate: [],
    }

    for (const smLayout of currentSmLayout || []) {
        // leave the new tile and anything above the insertion point untouched
        if (smLayout.i === `${newTileId}` || smLayout.y < targetY) {
            continue
        }
        // only push tiles that share horizontal space with the inserted tile's column span
        const overlapsColumn = smLayout.x < targetX + w && smLayout.x + smLayout.w > targetX
        if (!overlapsColumn) {
            continue
        }

        result.tilesToUpdate.push({
            id: Number(smLayout.i),
            layouts: {
                sm: { x: smLayout.x, y: smLayout.y + h, w: smLayout.w, h: smLayout.h },
            },
        })
    }

    return result
}

function canPlaceToRight(
    layouts: Layout,
    excludeTileId: number,
    x: number,
    y: number,
    w: number,
    h: number,
    columnCount: number
): boolean {
    const rightX = x + w
    if (rightX + w > columnCount) {
        return false
    }

    return !layouts.some((l) => {
        if (l.i === `${excludeTileId}`) {
            return false
        }
        const overlapsX = l.x < rightX + w && l.x + l.w > rightX
        const overlapsY = l.y < y + h && l.y + l.h > y
        return overlapsX && overlapsY
    })
}

export function defaultSmLayoutAtBottom(smLayout: Layout | undefined, w: number, h: number): TileLayout {
    let maxBottom = 0
    for (const layout of smLayout ?? []) {
        maxBottom = Math.max(maxBottom, (layout.y ?? 0) + (layout.h ?? 0))
    }

    return { x: 0, y: maxBottom, w, h }
}

export const sortTilesByLayout = (
    tiles: Array<DashboardTile<QueryBasedInsightModel>>,
    col: DashboardLayoutSize
): Array<DashboardTile<QueryBasedInsightModel>> => {
    return [...tiles].sort((a: DashboardTile<QueryBasedInsightModel>, b: DashboardTile<QueryBasedInsightModel>) => {
        const ax = a.layouts?.[col]?.x ?? 0
        const ay = a.layouts?.[col]?.y ?? 0
        const bx = b.layouts?.[col]?.x ?? 0
        const by = b.layouts?.[col]?.y ?? 0

        if (ay < by || (ay == by && ax < bx)) {
            return -1
        } else if (ay > by || (ay == by && ax > bx)) {
            return 1
        }
        return 0
    })
}
export const calculateLayouts = (
    tiles: DashboardTile<QueryBasedInsightModel>[]
): Partial<Record<DashboardLayoutSize, Layout>> => {
    const allLayouts: Partial<Record<keyof typeof BREAKPOINT_COLUMN_COUNTS, Layout>> = {}

    // Always calculate sm layout first to establish reference order
    let referenceOrder: number[] | undefined = undefined

    for (const breakpoint of Object.keys(BREAKPOINT_COLUMN_COUNTS) as (keyof typeof BREAKPOINT_COLUMN_COUNTS)[]) {
        const columnCount = BREAKPOINT_COLUMN_COUNTS[breakpoint]

        let sortedDashboardTiles: DashboardTile<QueryBasedInsightModel>[] | undefined
        if (referenceOrder === undefined) {
            sortedDashboardTiles = sortTilesByLayout(tiles, 'sm')
        } else {
            // Subsequent passes: follow the reference order from sm layout
            sortedDashboardTiles = tiles.sort((a, b) => {
                return (referenceOrder?.indexOf(a.id) || 0) - (referenceOrder?.indexOf(b.id) || 0)
            })
        }

        const layouts = (sortedDashboardTiles || []).map((tile) => {
            const query = tile.insight ? getQueryBasedInsightModel(tile.insight) : null
            // Base constraints
            let defaultW = 6
            let defaultH = 5
            // Content-adjusted constraints (note that widths should be factors of 12)
            if (tile.text) {
                defaultW = DEFAULT_TEXT_TILE_SIZE.w
                defaultH = DEFAULT_TEXT_TILE_SIZE.h
            } else if (isFunnelsQuery(query)) {
                defaultW = 4
                defaultH = 4
            } else if (isRetentionQuery(query)) {
                defaultW = 6
                defaultH = 7
            } else if (isPathsQuery(query)) {
                defaultW = columnCount // Paths take up so much space that they need to be full width to be readable
                defaultH = 7
            } else if (isTrendsQuery(query) && query.trendsFilter?.display === ChartDisplayType.BoldNumber) {
                defaultW = 2
                defaultH = 2
            } else if (isTrendsQuery(query) && query.trendsFilter?.display === ChartDisplayType.Metric) {
                defaultW = 3
                defaultH = 3
            }
            // Single-column layout width override
            if (breakpoint === 'xs') {
                defaultW = 1
            }

            // For xs layout, ignore stored layout and derive from sm order
            // For sm layout, use stored layout if available
            const layout = breakpoint === 'xs' ? undefined : tile.layouts?.[breakpoint]
            const { x, y, w, h } = layout || {}

            const isTextTile = !!tile.text
            const isButtonTile = !!tile.button_tile
            const isWidgetTile = !!tile.widget
            const widgetCatalogLayout = isWidgetTile ? getWidgetCatalogLayout(tile.widget?.widget_type) : undefined
            if (isButtonTile) {
                defaultW = 3
                defaultH = 1
            } else if (isWidgetTile) {
                defaultW = widgetCatalogLayout?.w ?? 6
                defaultH = widgetCatalogLayout?.h ?? 5
            }
            const xsSmH = breakpoint === 'xs' ? tile.layouts?.sm?.h : undefined
            const realW = Math.min(w || defaultW, columnCount)
            const realH = h || (typeof xsSmH === 'number' && xsSmH > 0 ? xsSmH : undefined) || defaultH
            const { minW, minH } = getTileMinDimensions({
                isTextTile,
                isButtonTile,
                isWidgetTile,
                widgetCatalogLayout,
            })

            return {
                i: tile.id?.toString(),
                x: x != null && Number.isInteger(x) && x + realW - 1 < columnCount ? x : 0,
                y: y != null && Number.isInteger(y) ? y : Infinity,
                w: realW,
                h: realH,
                minW,
                minH,
            }
        })

        const cleanLayouts = layouts?.filter(({ y }) => y !== Infinity)
        const dirtyLayouts = layouts?.filter(({ y }) => y === Infinity)

        // array of -1 for each column
        const lowestPoints = Array.from(Array(columnCount)).map(() => -1)

        // set the lowest point for each column
        for (const { x, y, w, h } of cleanLayouts) {
            for (let i = x; i <= x + w - 1; i++) {
                lowestPoints[i] = Math.max(lowestPoints[i], y + h - 1)
            }
        }

        for (const { i, w, h, minW, minH } of dirtyLayouts) {
            // how low are things in "w" consecutive of columns
            const segmentCount = columnCount - w + 1
            const lowestSegments = Array.from(Array(segmentCount)).map(() => -1)
            for (let k = 0; k < segmentCount; k++) {
                for (let j = k; j <= k + w - 1; j++) {
                    lowestSegments[k] = Math.max(lowestSegments[k], lowestPoints[j])
                }
            }

            let lowestIndex = 0
            let lowestDepth = lowestSegments[0]
            for (let index = 1; index < segmentCount; index++) {
                const depth = lowestSegments[index]
                if (depth < lowestDepth) {
                    lowestIndex = index
                    lowestDepth = depth
                }
            }

            cleanLayouts.push({
                i,
                x: lowestIndex,
                y: lowestDepth + 1,
                w,
                h,
                minW,
                minH,
            })

            for (let k = lowestIndex; k <= lowestIndex + w - 1; k++) {
                lowestPoints[k] = Math.max(lowestPoints[k], lowestDepth + h)
            }
        }

        if (breakpoint === 'sm') {
            referenceOrder = [...cleanLayouts]
                .sort((a, b) => (a.y === b.y ? a.x - b.x : a.y - b.y))
                .map((l) => Number(l.i))
        }

        allLayouts[breakpoint] = cleanLayouts
    }

    return allLayouts
}
