import { Layout } from 'react-grid-layout'
import { BREAKPOINT_COLUMN_COUNTS, MIN_ITEM_HEIGHT_UNITS, MIN_ITEM_WIDTH_UNITS } from 'scenes/dashboard/dashboardLogic'
import { isPathsFilter, isRetentionFilter, isTrendsFilter } from 'scenes/insights/sharedUtils'

import { ChartDisplayType, DashboardLayoutSize, DashboardTile, FilterType } from '~/types'

export const sortTilesByLayout = (tiles: Array<DashboardTile>, col: DashboardLayoutSize): Array<DashboardTile> => {
    return [...tiles].sort((a: DashboardTile, b: DashboardTile) => {
        const ax = a.layouts[col]?.x ?? 0
        const ay = a.layouts[col]?.y ?? 0
        const bx = b.layouts[col]?.x ?? 0
        const by = b.layouts[col]?.y ?? 0

        if (ay < by || (ay == by && ax < bx)) {
            return -1
        } else if (ay > by || (ay == by && ax > bx)) {
            return 1
        } else {
            return 0
        }
    })
}
export const calculateLayouts = (tiles: DashboardTile[]): Partial<Record<DashboardLayoutSize, Layout[]>> => {
    const allLayouts: Partial<Record<keyof typeof BREAKPOINT_COLUMN_COUNTS, Layout[]>> = {}

    let referenceOrder: number[] | undefined = undefined

    for (const col of Object.keys(BREAKPOINT_COLUMN_COUNTS) as (keyof typeof BREAKPOINT_COLUMN_COUNTS)[]) {
        // The dashboard redesign includes constraints on the size of dashboard items
        const minW = col === 'xs' ? 1 : MIN_ITEM_WIDTH_UNITS
        const minH = MIN_ITEM_HEIGHT_UNITS

        let sortedDashboardTiles: DashboardTile[] | undefined
        if (referenceOrder === undefined) {
            sortedDashboardTiles = sortTilesByLayout(tiles, col)
            referenceOrder = sortedDashboardTiles.map((tile) => tile.id)
        } else {
            sortedDashboardTiles = tiles.sort((a, b) => {
                return (referenceOrder?.indexOf(a.id) || 0) - (referenceOrder?.indexOf(b.id) || 0)
            })
        }

        const layouts = (sortedDashboardTiles || []).map((tile) => {
            const filters: Partial<FilterType> | undefined = tile.insight?.filters
            const isRetention = isRetentionFilter(filters)
            const isPathsViz = isPathsFilter(filters)
            const isBoldNumber = isTrendsFilter(filters) && filters.display === ChartDisplayType.BoldNumber

            const defaultWidth = isRetention || isPathsViz ? 8 : 6
            const defaultHeight = tile.text ? minH + 1 : isRetention ? 8 : isPathsViz ? 12.5 : 5
            const layout = tile.layouts && tile.layouts[col]
            const { x, y, w, h } = layout || {}
            const width = Math.min(w || defaultWidth, BREAKPOINT_COLUMN_COUNTS[col])

            return {
                i: tile.id?.toString(),
                x: Number.isInteger(x) && x + width - 1 < BREAKPOINT_COLUMN_COUNTS[col] ? x : 0,
                y: Number.isInteger(y) ? y : Infinity,
                w: width,
                h: h || defaultHeight,
                minW,
                minH: tile.text ? 2 : isBoldNumber ? 4 : minH,
            }
        })

        const cleanLayouts = layouts?.filter(({ y }) => y !== Infinity)

        // array of -1 for each column
        const lowestPoints = Array.from(Array(BREAKPOINT_COLUMN_COUNTS[col])).map(() => -1)

        // set the lowest point for each column
        cleanLayouts?.forEach(({ x, y, w, h }) => {
            for (let i = x; i <= x + w - 1; i++) {
                lowestPoints[i] = Math.max(lowestPoints[i], y + h - 1)
            }
        })

        layouts
            ?.filter(({ y }) => y === Infinity)
            .forEach(({ i, w, h }) => {
                // how low are things in "w" consecutive of columns
                const segmentCount = BREAKPOINT_COLUMN_COUNTS[col] - w + 1
                const lowestSegments = Array.from(Array(segmentCount)).map(() => -1)
                for (let k = 0; k < segmentCount; k++) {
                    for (let j = k; j <= k + w - 1; j++) {
                        lowestSegments[k] = Math.max(lowestSegments[k], lowestPoints[j])
                    }
                }

                let lowestIndex = 0
                let lowestDepth = lowestSegments[0]

                lowestSegments.forEach((depth, index) => {
                    if (depth < lowestDepth) {
                        lowestIndex = index
                        lowestDepth = depth
                    }
                })

                cleanLayouts?.push({
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
            })

        allLayouts[col] = cleanLayouts
    }

    return allLayouts
}
