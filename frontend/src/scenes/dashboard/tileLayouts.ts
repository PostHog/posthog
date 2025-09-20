import { Layout } from 'react-grid-layout'

import { BREAKPOINT_COLUMN_COUNTS } from 'scenes/dashboard/dashboardUtils'

import { getQueryBasedInsightModel } from '~/queries/nodes/InsightViz/utils'
import { isFunnelsQuery, isPathsQuery, isRetentionQuery, isTrendsQuery } from '~/queries/utils'
import { ChartDisplayType, DashboardLayoutSize, DashboardTile, QueryBasedInsightModel } from '~/types'

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
): Partial<Record<DashboardLayoutSize, Layout[]>> => {
    const allLayouts: Partial<Record<keyof typeof BREAKPOINT_COLUMN_COUNTS, Layout[]>> = {}

    let referenceOrder: number[] | undefined = undefined

    for (const breakpoint of Object.keys(BREAKPOINT_COLUMN_COUNTS) as (keyof typeof BREAKPOINT_COLUMN_COUNTS)[]) {
        const columnCount = BREAKPOINT_COLUMN_COUNTS[breakpoint]

        let sortedDashboardTiles: DashboardTile<QueryBasedInsightModel>[] | undefined
        if (referenceOrder === undefined) {
            sortedDashboardTiles = sortTilesByLayout(tiles, breakpoint)
            referenceOrder = sortedDashboardTiles.map((tile) => tile.id)
        } else {
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
                defaultW = 2
                defaultH = 2
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
            }
            // Single-column layout width override
            if (breakpoint === 'xs') {
                defaultW = 1
            }

            const layout = tile.layouts && tile.layouts[breakpoint]
            const { x, y, w, h } = layout || {}

            const realW = Math.min(w || defaultW, columnCount)
            const realH = h || defaultH

            return {
                i: tile.id?.toString(),
                x: x != null && Number.isInteger(x) && x + realW - 1 < columnCount ? x : 0,
                y: y != null && Number.isInteger(y) ? y : Infinity,
                w: realW,
                h: realH,
                minW: 1,
                minH: 1,
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
