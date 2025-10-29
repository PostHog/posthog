import {
    DataTableNode,
    EventsHeatMapDataResult,
    InsightVizNode,
    NodeKind,
    TrendsQueryResponse,
    WebStatsBreakdown,
    WebStatsTableQueryResponse,
} from '~/queries/schema/schema-general'

import {
    CalendarHeatmapAdapter,
    TrendsAdapter,
    WebAnalyticsTableAdapter,
    WorldMapAdapter,
} from './webAnalyticsExportUtils'

describe('WebAnalyticsExport adapters', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    describe('CalendarHeatmapAdapter', () => {
        it('converts calendar heatmap data to table format', () => {
            const response: TrendsQueryResponse = {
                results: [
                    {
                        calendar_heatmap_data: {
                            data: [
                                { row: 0, column: 0, value: 10 },
                                { row: 0, column: 1, value: 15 },
                                { row: 1, column: 0, value: 20 },
                                { row: 1, column: 1, value: 25 },
                            ],
                            rowAggregations: [
                                { row: 0, value: 25 },
                                { row: 1, value: 45 },
                            ],
                            columnAggregations: [
                                { column: 0, value: 30 },
                                { column: 1, value: 40 },
                            ],
                            allAggregations: 70,
                        },
                    },
                ],
            }
            const query: InsightVizNode = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    series: [],
                },
            }

            const adapter = new CalendarHeatmapAdapter(response, query)
            const result = adapter.toTableData()

            expect(result).toEqual([
                [
                    '',
                    '0',
                    '1',
                    '2',
                    '3',
                    '4',
                    '5',
                    '6',
                    '7',
                    '8',
                    '9',
                    '10',
                    '11',
                    '12',
                    '13',
                    '14',
                    '15',
                    '16',
                    '17',
                    '18',
                    '19',
                    '20',
                    '21',
                    '22',
                    '23',
                    'All',
                ],
                [
                    'Sun',
                    '10',
                    '15',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '25',
                ],
                [
                    'Mon',
                    '20',
                    '25',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '45',
                ],
                [
                    'Tue',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '',
                ],
                [
                    'Wed',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '',
                ],
                [
                    'Thu',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '',
                ],
                [
                    'Fri',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '',
                ],
                [
                    'Sat',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '',
                ],
                [
                    'All',
                    '30',
                    '40',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '0',
                    '70',
                ],
            ])
        })

        it('handles sparse data with missing cells', () => {
            const response: TrendsQueryResponse = {
                results: [
                    {
                        calendar_heatmap_data: {
                            data: [{ row: 0, column: 1, value: 15 }],
                            rowAggregations: [{ row: 0, value: 15 }],
                            columnAggregations: [{ column: 1, value: 15 }],
                            allAggregations: 15,
                        },
                    },
                ],
            }
            const query: InsightVizNode = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    series: [],
                },
            }

            const adapter = new CalendarHeatmapAdapter(response, query)
            const result = adapter.toTableData()

            expect(result).toHaveLength(9) // 1 header + 7 data rows + 1 aggregation row
            expect(result[0]).toHaveLength(26) // empty + 24 hours + All
            expect(result[1][1]).toBe('0') // Sun, hour 0
            expect(result[1][2]).toBe('15') // Sun, hour 1
            expect(result[1][25]).toBe('15') // Sun, row total
        })

        it('handles empty heatmap data', () => {
            const response: TrendsQueryResponse = {
                results: [
                    {
                        calendar_heatmap_data: {
                            data: [],
                            rowAggregations: [],
                            columnAggregations: [],
                            allAggregations: 0,
                        },
                    },
                ],
            }
            const query: InsightVizNode = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    series: [],
                },
            }

            const adapter = new CalendarHeatmapAdapter(response, query)
            const result = adapter.toTableData()

            expect(result).toHaveLength(9) // 1 header + 7 data rows + 1 aggregation row
            expect(result[0]).toHaveLength(26) // empty + 24 hours + All
            expect(result[8][25]).toBe('0') // All row, All column
        })

        it('returns empty array when heatmap data is missing', () => {
            const response: TrendsQueryResponse = {
                results: [{}],
            }
            const query: InsightVizNode = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    series: [],
                },
            }

            const adapter = new CalendarHeatmapAdapter(response, query)
            const result = adapter.toTableData()

            expect(result).toEqual([])
        })

        it('handles full day x hour matrix (7x24)', () => {
            const data: EventsHeatMapDataResult[] = []
            for (let row = 0; row < 7; row++) {
                for (let col = 0; col < 24; col++) {
                    data.push({ row, column: col, value: row * 24 + col })
                }
            }

            const response: TrendsQueryResponse = {
                results: [
                    {
                        calendar_heatmap_data: {
                            data,
                            rowAggregations: Array.from({ length: 7 }, (_, i) => ({
                                row: i,
                                value: (i * 24 * (i * 24 + 23)) / 2,
                            })),
                            columnAggregations: Array.from({ length: 24 }, (_, i) => ({ column: i, value: i * 7 })),
                            allAggregations: 19656,
                        },
                    },
                ],
            }
            const query: InsightVizNode = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    series: [],
                },
            }

            const adapter = new CalendarHeatmapAdapter(response, query)
            const result = adapter.toTableData()

            expect(result.length).toBe(9) // 1 header + 7 data rows + 1 aggregation row
            expect(result[0].length).toBe(26) // empty + 24 hours + All
            expect(result[0][0]).toBe('')
            expect(result[0][1]).toBe('0')
            expect(result[0][24]).toBe('23')
            expect(result[0][25]).toBe('All')
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

    describe('TrendsAdapter', () => {
        it('converts trends data to table format', () => {
            const response: TrendsQueryResponse = {
                results: [
                    {
                        label: 'Pageview',
                        data: [10, 15, 20],
                        labels: ['2024-01-01', '2024-01-02', '2024-01-03'],
                    },
                    {
                        label: 'Button Click',
                        data: [5, 8, 12],
                        labels: ['2024-01-01', '2024-01-02', '2024-01-03'],
                    },
                ],
            }
            const query: InsightVizNode = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    series: [],
                },
            }

            const adapter = new TrendsAdapter(response, query)
            const result = adapter.toTableData()

            expect(result).toEqual([
                ['Date', 'Pageview', 'Button Click'],
                ['2024-01-01', '10', '5'],
                ['2024-01-02', '15', '8'],
                ['2024-01-03', '20', '12'],
            ])
        })

        it('uses custom_name when available', () => {
            const response: TrendsQueryResponse = {
                results: [
                    {
                        label: 'pageview',
                        action: { custom_name: 'Page Views' } as any,
                        data: [10, 15],
                        labels: ['2024-01-01', '2024-01-02'],
                    },
                ],
            }
            const query: InsightVizNode = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    series: [],
                },
            }

            const adapter = new TrendsAdapter(response, query)
            const result = adapter.toTableData()

            expect(result[0]).toEqual(['Date', 'Page Views'])
        })

        it('includes compare_label when present', () => {
            const response: TrendsQueryResponse = {
                results: [
                    {
                        label: 'Pageview',
                        compare_label: 'current',
                        data: [10, 15],
                        labels: ['2024-01-01', '2024-01-02'],
                    },
                    {
                        label: 'Pageview',
                        compare_label: 'previous',
                        data: [8, 12],
                        labels: ['2024-01-01', '2024-01-02'],
                    },
                ],
            }
            const query: InsightVizNode = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    series: [],
                },
            }

            const adapter = new TrendsAdapter(response, query)
            const result = adapter.toTableData()

            expect(result[0]).toEqual(['Date', 'Pageview (current)', 'Pageview (previous)'])
        })

        it('uses days as fallback for date labels', () => {
            const response: TrendsQueryResponse = {
                results: [
                    {
                        label: 'Event',
                        data: [10, 15],
                        days: ['2024-01-01', '2024-01-02'],
                    },
                ],
            }
            const query: InsightVizNode = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    series: [],
                },
            }

            const adapter = new TrendsAdapter(response, query)
            const result = adapter.toTableData()

            expect(result[1]).toEqual(['2024-01-01', '10'])
            expect(result[2]).toEqual(['2024-01-02', '15'])
        })

        it('returns empty array for empty results', () => {
            const response: TrendsQueryResponse = {
                results: [],
            }
            const query: InsightVizNode = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    series: [],
                },
            }

            const adapter = new TrendsAdapter(response, query)
            const result = adapter.toTableData()

            expect(result).toEqual([])
        })

        it('returns empty array when no date labels', () => {
            const response: TrendsQueryResponse = {
                results: [
                    {
                        label: 'Event',
                        data: [10, 15],
                    },
                ],
            }
            const query: InsightVizNode = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    series: [],
                },
            }

            const adapter = new TrendsAdapter(response, query)
            const result = adapter.toTableData()

            expect(result).toEqual([])
        })

        it('handles null values in data', () => {
            const response: TrendsQueryResponse = {
                results: [
                    {
                        label: 'Event',
                        data: [10, null, 20] as any,
                        labels: ['2024-01-01', '2024-01-02', '2024-01-03'],
                    },
                ],
            }
            const query: InsightVizNode = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    series: [],
                },
            }

            const adapter = new TrendsAdapter(response, query)
            const result = adapter.toTableData()

            expect(result).toEqual([
                ['Date', 'Event'],
                ['2024-01-01', '10'],
                ['2024-01-02', ''],
                ['2024-01-03', '20'],
            ])
        })

        it('uses breakdown_value when available instead of label', () => {
            const response: TrendsQueryResponse = {
                results: [
                    {
                        label: 'Unique visitors',
                        breakdown_value: 'Organic Search',
                        data: [335, 348],
                        labels: ['2024-01-01', '2024-01-02'],
                    } as any,
                    {
                        label: 'Unique visitors',
                        breakdown_value: 'Unknown',
                        data: [133, 113],
                        labels: ['2024-01-01', '2024-01-02'],
                    } as any,
                    {
                        label: 'Unique visitors',
                        breakdown_value: 'Organic Video',
                        data: [1, 2],
                        labels: ['2024-01-01', '2024-01-02'],
                    } as any,
                    {
                        label: 'Unique visitors',
                        breakdown_value: 'Direct',
                        data: [0, 0],
                        labels: ['2024-01-01', '2024-01-02'],
                    } as any,
                ],
            }
            const query: InsightVizNode = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    series: [],
                },
            }

            const adapter = new TrendsAdapter(response, query)
            const result = adapter.toTableData()

            expect(result[0]).toEqual(['Date', 'Organic Search', 'Unknown', 'Organic Video', 'Direct'])
            expect(result[1]).toEqual(['2024-01-01', '335', '133', '1', '0'])
            expect(result[2]).toEqual(['2024-01-02', '348', '113', '2', '0'])
        })
    })

    describe('WorldMapAdapter', () => {
        it('converts world map data to table format', () => {
            const response: TrendsQueryResponse = {
                results: [
                    {
                        label: 'US',
                        aggregated_value: 45319,
                        data: [],
                        days: [],
                    } as any,
                    {
                        label: 'GB',
                        aggregated_value: 12345,
                        data: [],
                        days: [],
                    } as any,
                    {
                        label: 'CA',
                        aggregated_value: 8765,
                        data: [],
                        days: [],
                    } as any,
                ],
            }
            const query: InsightVizNode = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    series: [],
                },
            }

            const adapter = new WorldMapAdapter(response, query)
            const result = adapter.toTableData()

            expect(result).toEqual([
                ['Country', 'Visitors'],
                ['US', '45319'],
                ['GB', '12345'],
                ['CA', '8765'],
            ])
        })

        it('handles empty results', () => {
            const response: TrendsQueryResponse = {
                results: [],
            }
            const query: InsightVizNode = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    series: [],
                },
            }

            const adapter = new WorldMapAdapter(response, query)
            const result = adapter.toTableData()

            expect(result).toEqual([])
        })

        it('handles missing aggregated_value with fallback to count', () => {
            const response: TrendsQueryResponse = {
                results: [
                    {
                        label: 'US',
                        count: 100,
                        data: [],
                        days: [],
                    } as any,
                ],
            }
            const query: InsightVizNode = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    series: [],
                },
            }

            const adapter = new WorldMapAdapter(response, query)
            const result = adapter.toTableData()

            expect(result).toEqual([
                ['Country', 'Visitors'],
                ['US', '100'],
            ])
        })

        it('handles missing label', () => {
            const response: TrendsQueryResponse = {
                results: [
                    {
                        aggregated_value: 50,
                        data: [],
                        days: [],
                    } as any,
                ],
            }
            const query: InsightVizNode = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    series: [],
                },
            }

            const adapter = new WorldMapAdapter(response, query)
            const result = adapter.toTableData()

            expect(result).toEqual([
                ['Country', 'Visitors'],
                ['', '50'],
            ])
        })
    })
})
