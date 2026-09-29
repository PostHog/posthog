import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/insightVizKeys'
import {
    DataTableNode,
    NodeKind,
    WebStatsBreakdown,
    WebStatsTableQueryResponse,
    WebVitalsPathBreakdownQuery,
    WebVitalsPathBreakdownQueryResponse,
    WebVitalsQuery,
    WebVitalsQueryResponse,
} from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { InsightLogicProps, PropertyMathType } from '~/types'

import { TileId, WebAnalyticsTile } from './common'
import {
    WebAnalyticsTableAdapter,
    buildCsvFilenames,
    collectAllTilesTableData,
    getExportAdapter,
} from './webAnalyticsExportUtils'

const webVitalsQuery: WebVitalsQuery = {
    kind: NodeKind.WebVitalsQuery,
    properties: [],
    source: {
        kind: NodeKind.TrendsQuery,
        series: [],
    },
}

const webVitalsResponse: WebVitalsQueryResponse = {
    results: [
        {
            action: { custom_name: 'LCP', math: PropertyMathType.P90 },
            days: ['2026-09-01', '2026-09-02'],
            data: [2400, 2600],
        },
        {
            action: { custom_name: 'CLS', math: PropertyMathType.P90 },
            days: ['2026-09-01', '2026-09-02'],
            data: [0.04, 0.05],
        },
    ],
}

const pathBreakdownQuery: WebVitalsPathBreakdownQuery = {
    kind: NodeKind.WebVitalsPathBreakdownQuery,
    dateRange: { date_from: '-7d' },
    properties: [],
    percentile: PropertyMathType.P90,
    metric: 'FCP',
    thresholds: [1800, 3000],
}

const pathBreakdownResponse: WebVitalsPathBreakdownQueryResponse = {
    results: [
        {
            good: [{ path: '/pricing', value: 900 }],
            needs_improvements: [],
            poor: [{ path: '/', value: 13320 }],
        },
    ],
}

describe('WebAnalyticsExport adapters', () => {
    describe('buildCsvFilenames', () => {
        it('slugifies titles and de-duplicates colliding stems so no zip entry is overwritten', () => {
            expect(buildCsvFilenames(['Top paths', 'Sources', 'Sources', 'Referring domains: Sources'])).toEqual([
                'top-paths.csv',
                'sources.csv',
                'sources-2.csv',
                'referring-domains-sources.csv',
            ])
        })

        it('falls back to a usable stem when a title has no alphanumerics', () => {
            expect(buildCsvFilenames(['—', '///'])).toEqual(['tile.csv', 'tile-2.csv'])
        })
    })

    describe('WebAnalyticsTableAdapter', () => {
        it('converts web analytics table data without comparison', () => {
            const response: WebStatsTableQueryResponse = {
                results: [
                    ['/home', 100, 50],
                    ['/about', 75, 30],
                ],
                columns: ['context.columns.pathname', 'context.columns.visitors', 'context.columns.views'],
            }
            const query: DataTableNode = {
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.WebStatsTableQuery,
                    breakdownBy: WebStatsBreakdown.Page,
                    dateRange: { date_from: '-7d' },
                    properties: [],
                },
            }

            const adapter = new WebAnalyticsTableAdapter(response, query)
            const result = adapter.toTableData()

            expect(result).toEqual([
                ['pathname', 'Visitors', 'Views'],
                ['/home', '100', '50'],
                ['/about', '75', '30'],
            ])
        })

        it('converts web analytics table data with comparison', () => {
            const response: WebStatsTableQueryResponse = {
                results: [
                    ['/home', [100, 90], [50, 45]],
                    ['/about', [75, 70], [30, 28]],
                ],
                columns: ['context.columns.pathname', 'context.columns.visitors', 'context.columns.views'],
            }
            const query: DataTableNode = {
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.WebStatsTableQuery,
                    breakdownBy: WebStatsBreakdown.Page,
                    dateRange: { date_from: '-7d' },
                    properties: [],
                    compareFilter: { compare: true },
                },
            }

            const adapter = new WebAnalyticsTableAdapter(response, query)
            const result = adapter.toTableData()

            expect(result).toEqual([
                ['pathname', 'Visitors (current)', 'Visitors (previous)', 'Views (current)', 'Views (previous)'],
                ['/home', '100', '90', '50', '45'],
                ['/about', '75', '70', '30', '28'],
            ])
        })

        it('returns empty array for empty results', () => {
            const response: WebStatsTableQueryResponse = {
                results: [],
                columns: [],
            }
            const query: DataTableNode = {
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.WebStatsTableQuery,
                    breakdownBy: WebStatsBreakdown.Page,
                    dateRange: { date_from: '-7d' },
                    properties: [],
                },
            }

            const adapter = new WebAnalyticsTableAdapter(response, query)
            const result = adapter.toTableData()

            expect(result).toEqual([])
        })

        it('handles null values in data', () => {
            const response: WebStatsTableQueryResponse = {
                results: [['/home', null, 50]],
                columns: ['context.columns.pathname', 'context.columns.visitors', 'context.columns.views'],
            }
            const query: DataTableNode = {
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.WebStatsTableQuery,
                    breakdownBy: WebStatsBreakdown.Page,
                    dateRange: { date_from: '-7d' },
                    properties: [],
                },
            }

            const adapter = new WebAnalyticsTableAdapter(response, query)
            const result = adapter.toTableData()

            expect(result).toEqual([
                ['pathname', 'Visitors', 'Views'],
                ['/home', '', '50'],
            ])
        })
    })

    describe('web vitals adapters', () => {
        it.each([
            {
                name: 'timeseries',
                response: webVitalsResponse,
                query: webVitalsQuery,
                expected: [
                    ['Date', 'LCP p90 (ms)', 'CLS p90'],
                    ['2026-09-01', '2400', '0.04'],
                    ['2026-09-02', '2600', '0.05'],
                ],
            },
            {
                name: 'timeseries without results',
                response: { results: [] },
                query: webVitalsQuery,
                expected: [],
            },
            {
                name: 'path breakdown',
                response: pathBreakdownResponse,
                query: pathBreakdownQuery,
                expected: [
                    ['Band', 'Path', 'FCP p90 (ms)'],
                    ['Great', '/pricing', '900'],
                    ['Poor', '/', '13320'],
                ],
            },
            {
                name: 'path breakdown without paths',
                response: { results: [{ good: [], needs_improvements: [], poor: [] }] },
                query: pathBreakdownQuery,
                expected: [],
            },
        ])('converts $name', ({ response, query, expected }) => {
            expect(getExportAdapter(response, query)?.toTableData()).toEqual(expected)
        })

        it('collects the web vitals tiles from their mounted data node logics', () => {
            initKeaTests()
            const webVitalsInsightProps: InsightLogicProps = { dashboardItemId: 'new-web-vitals-tile' }
            const pathBreakdownInsightProps: InsightLogicProps = { dashboardItemId: 'new-web-vitals-path-tile' }
            const tiles: WebAnalyticsTile[] = [
                {
                    kind: 'query',
                    tileId: TileId.WEB_VITALS,
                    layout: {},
                    query: webVitalsQuery,
                    insightProps: webVitalsInsightProps,
                },
                {
                    kind: 'query',
                    tileId: TileId.WEB_VITALS_PATH_BREAKDOWN,
                    layout: {},
                    query: pathBreakdownQuery,
                    insightProps: pathBreakdownInsightProps,
                },
            ]
            dataNodeLogic({
                key: insightVizDataNodeKey(webVitalsInsightProps),
                query: webVitalsQuery,
                cachedResults: webVitalsResponse,
            }).mount()
            dataNodeLogic({
                key: insightVizDataNodeKey(pathBreakdownInsightProps),
                query: pathBreakdownQuery,
                cachedResults: pathBreakdownResponse,
            }).mount()

            expect(collectAllTilesTableData(tiles).map(({ title, tableData }) => [title, tableData.length])).toEqual([
                ['Web vitals', 3],
                ['Web vitals path breakdown: FCP', 3],
            ])
        })
    })
})
