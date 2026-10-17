import { NodeKind, QuerySchema, WebStatsBreakdown } from '~/queries/schema/schema-general'

import { TileId, WebAnalyticsTile } from './common'
import { applyWebQueryModifiers } from './webQueryModifiers'

const overview: QuerySchema = {
    kind: NodeKind.WebOverviewQuery,
    properties: [],
    useWebAnalyticsPrecompute: true,
}
const statsTable: QuerySchema = {
    kind: NodeKind.DataTableNode,
    source: { kind: NodeKind.WebStatsTableQuery, properties: [], breakdownBy: WebStatsBreakdown.Page },
}
const trends: QuerySchema = {
    kind: NodeKind.InsightVizNode,
    source: { kind: NodeKind.TrendsQuery, series: [] },
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
    { kind: 'query', tileId: TileId.GRAPHS, layout, query: trends, insightProps },
    { kind: 'replay', tileId: TileId.REPLAY, layout },
]

describe('applyWebQueryModifiers', () => {
    it('keeps the same tiles when there are no modifiers', () => {
        expect(applyWebQueryModifiers(tiles, {})).toBe(tiles)
    })

    it('sets the modifiers on web analytics queries only, including wrapped sources inside sections and tabs', () => {
        const [overviewTile, sectionTile, trendsTile, replayTile] = applyWebQueryModifiers(tiles, {
            useDimensionalTables: true,
        })

        expect(overviewTile).toMatchObject({
            query: { useWebAnalyticsPrecompute: true, webQueryModifiers: { useDimensionalTables: true } },
        })
        expect(sectionTile).toMatchObject({
            tiles: [{ tabs: [{ query: { source: { webQueryModifiers: { useDimensionalTables: true } } } }] }],
        })
        // TrendsQuery does not accept the field, so the backend would reject the whole tile.
        expect(trendsTile).toMatchObject({ query: { source: trends.source } })
        expect((trendsTile as { query: { source: object } }).query.source).not.toHaveProperty('webQueryModifiers')
        expect(replayTile).toBe(tiles[3])
    })
})
