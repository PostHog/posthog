import { Layout } from 'react-grid-layout'
import { BREAKPOINT_COLUMN_COUNTS } from 'scenes/dashboard/dashboardLogic'
import { isFunnelsFilter, isPathsFilter, isRetentionFilter, isTrendsFilter } from 'scenes/insights/sharedUtils'

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

    for (const breakpoint of Object.keys(BREAKPOINT_COLUMN_COUNTS) as (keyof typeof BREAKPOINT_COLUMN_COUNTS)[]) {
        const columnCount = BREAKPOINT_COLUMN_COUNTS[breakpoint]

        let sortedDashboardTiles: DashboardTile[] | undefined
        if (referenceOrder === undefined) {
            sortedDashboardTiles = sortTilesByLayout(tiles, breakpoint)
            referenceOrder = sortedDashboardTiles.map((tile) => tile.id)
        } else {
            sortedDashboardTiles = tiles.sort((a, b) => {
                return (referenceOrder?.indexOf(a.id) || 0) - (referenceOrder?.indexOf(b.id) || 0)
            })
        }

        const layouts = (sortedDashboardTiles || []).map((tile) => {
            const filters: Partial<FilterType> | undefined = tile.insight?.filters
            // Base constraints
            let minW = 3
            let minH = 3
            let defaultW = 6
            let defaultH = 5
            // Content-adjusted constraints (note that widths should be factors of 12)
            if (tile.text) {
                minW = 1
                minH = 1
                defaultH = 2
            } else if (isFunnelsFilter(filters)) {
                minW = 4
                minH = 4
            } else if (isRetentionFilter(filters)) {
                minW = 6
                minH = 7
                defaultW = 6
                defaultH = 7
            } else if (isPathsFilter(filters)) {
                minW = columnCount // Paths take up so much space that they need to be full width to be readable
                minH = 7
                defaultW = columnCount
                defaultH = 7
            } else if (isTrendsFilter(filters) && filters.display === ChartDisplayType.BoldNumber) {
                minW = 2
                minH = 2
            }
            // Single-column layout width override
            if (breakpoint === 'xs') {
                minW = 1
                defaultW = 1
            }

            const layout = tile.layouts && tile.layouts[breakpoint]
            const { x, y, w, h } = layout || {}

            const realW = Math.min(w || defaultW, columnCount)
            const realH = h || defaultH

            return {
                i: tile.id?.toString(),
                x: Number.isInteger(x) && x + realW - 1 < columnCount ? x : 0,
                y: Number.isInteger(y) ? y : Infinity,
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

        allLayouts[breakpoint] = cleanLayouts
    }

    return allLayouts
}
