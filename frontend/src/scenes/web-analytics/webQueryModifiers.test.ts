import { NodeKind, QuerySchema, WebStatsBreakdown } from '~/queries/schema/schema-general'

import { TileId, WebAnalyticsTile } from './common'
import { applyWebQueryModifiers } from './webQueryModifiers'

const overview: QuerySchema = {
    kind: NodeKind.WebOverviewQuery,
    properties: [],
    modifiers: { convertToProjectTimezone: false },
}
const statsTable: QuerySchema = {
    kind: NodeKind.DataTableNode,
    source: { kind: NodeKind.WebStatsTableQuery, properties: [], breakdownBy: WebStatsBreakdown.Page },
}

const layout = { colSpanClassName: 'md:col-span-full' as const }
const insightProps = { dashboardItemId: 'new-test' as const }

const tiles: WebAnalyticsTile[] = [
    { kind: 'query', tileId: TileId.OVERVIEW, layout, query: overview, insightProps },
    {
        kind: 'section',
        tileId: TileId.PATHS,
        layout,
        tiles: [
            {
                kind: 'tabs',
                tileId: TileId.PATHS,
                layout,
                activeTabId: 'paths',
                setTabId: () => {},
                tabs: [{ id: 'paths', title: 'Paths', linkText: 'Paths', query: statsTable, insightProps }],
            },
        ],
    },
    { kind: 'replay', tileId: TileId.REPLAY, layout },
]

describe('applyWebQueryModifiers', () => {
    it('keeps the same tiles when there are no modifiers', () => {
        expect(applyWebQueryModifiers(tiles, {})).toBe(tiles)
    })

    it('merges modifiers into every query, including wrapped sources inside sections and tabs', () => {
        const [overviewTile, sectionTile, replayTile] = applyWebQueryModifiers(tiles, {
            useWebAnalyticsDimensionalTables: true,
        })

        expect(overviewTile).toMatchObject({
            query: { modifiers: { convertToProjectTimezone: false, useWebAnalyticsDimensionalTables: true } },
        })
        expect(sectionTile).toMatchObject({
            tiles: [
                {
                    tabs: [
                        {
                            query: {
                                kind: NodeKind.DataTableNode,
                                source: { modifiers: { useWebAnalyticsDimensionalTables: true } },
                            },
                        },
                    ],
                },
            ],
        })
        expect(replayTile).toBe(tiles[2])
    })
})
