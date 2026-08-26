import { DataTableNode, NodeKind, WebStatsBreakdown, WebStatsTableQueryResponse } from '~/queries/schema/schema-general'

import { WebAnalyticsTableAdapter, buildCsvFilenames } from './webAnalyticsExportUtils'

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
})
