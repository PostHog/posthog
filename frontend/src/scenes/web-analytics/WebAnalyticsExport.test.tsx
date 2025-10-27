import {
    EventsHeatMapDataResult,
    NodeKind,
    TrendsQueryResponse,
    WebStatsBreakdown,
    WebStatsTableQuery,
    WebStatsTableQueryResponse,
    WebTrendsMetric,
    WebTrendsQuery,
    WebTrendsQueryResponse,
} from '~/queries/schema/schema-general'

import {
    getCalendarHeatmapTableData,
    getTrendsTableData,
    getWebAnalyticsTableData,
    getWebTrendsTableData,
} from './webAnalyticsExportUtils'

describe('WebAnalyticsExport helper functions', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    describe('getCalendarHeatmapTableData', () => {
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
            const rowLabels = ['Sun', 'Mon']
            const columnLabels = ['0', '1']

            const result = getCalendarHeatmapTableData(response, rowLabels, columnLabels)

            expect(result).toEqual([
                ['', '0', '1', 'All'],
                ['Sun', '10', '15', '25'],
                ['Mon', '20', '25', '45'],
                ['All', '30', '40', '70'],
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
            const rowLabels = ['Sun', 'Mon']
            const columnLabels = ['0', '1']

            const result = getCalendarHeatmapTableData(response, rowLabels, columnLabels)

            expect(result).toEqual([
                ['', '0', '1', 'All'],
                ['Sun', '0', '15', '15'],
                ['Mon', '0', '0', ''],
                ['All', '0', '15', '15'],
            ])
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
            const rowLabels = ['Sun', 'Mon']
            const columnLabels = ['0', '1']

            const result = getCalendarHeatmapTableData(response, rowLabels, columnLabels)

            expect(result).toEqual([
                ['', '0', '1', 'All'],
                ['Sun', '0', '0', ''],
                ['Mon', '0', '0', ''],
                ['All', '0', '0', '0'],
            ])
        })

        it('returns empty array when heatmap data is missing', () => {
            const response: TrendsQueryResponse = {
                results: [{}],
            }
            const rowLabels = ['Sun', 'Mon']
            const columnLabels = ['0', '1']

            const result = getCalendarHeatmapTableData(response, rowLabels, columnLabels)

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
            const rowLabels = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
            const columnLabels = Array.from({ length: 24 }, (_, i) => String(i))

            const result = getCalendarHeatmapTableData(response, rowLabels, columnLabels)

            expect(result.length).toBe(9) // 1 header + 7 data rows + 1 aggregation row
            expect(result[0].length).toBe(26) // empty + 24 hours + All
            expect(result[0][0]).toBe('')
            expect(result[0][1]).toBe('0')
            expect(result[0][24]).toBe('23')
            expect(result[0][25]).toBe('All')
        })
    })

    describe('getWebAnalyticsTableData', () => {
        it('converts web analytics table data without comparison', () => {
            const response: WebStatsTableQueryResponse = {
                results: [
                    ['/home', 100, 50],
                    ['/about', 75, 30],
                ],
                columns: ['context.columns.pathname', 'context.columns.visitors', 'context.columns.views'],
            }
            const columns = ['context.columns.pathname', 'context.columns.visitors', 'context.columns.views']
            const query: WebStatsTableQuery = {
                kind: NodeKind.WebStatsTableQuery,
                breakdownBy: WebStatsBreakdown.Page,
                dateRange: { date_from: '-7d' },
                properties: [],
            }

            const result = getWebAnalyticsTableData(response, columns, query)

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
            const columns = ['context.columns.pathname', 'context.columns.visitors', 'context.columns.views']
            const query: WebStatsTableQuery = {
                kind: NodeKind.WebStatsTableQuery,
                breakdownBy: WebStatsBreakdown.Page,
                dateRange: { date_from: '-7d' },
                properties: [],
                compareFilter: { compare: true },
            }

            const result = getWebAnalyticsTableData(response, columns, query)

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
            const query: WebStatsTableQuery = {
                kind: NodeKind.WebStatsTableQuery,
                breakdownBy: WebStatsBreakdown.Page,
                dateRange: { date_from: '-7d' },
                properties: [],
            }

            const result = getWebAnalyticsTableData(response, [], query)

            expect(result).toEqual([])
        })

        it('handles null values in data', () => {
            const response: WebStatsTableQueryResponse = {
                results: [['/home', null, 50]],
                columns: ['context.columns.pathname', 'context.columns.visitors', 'context.columns.views'],
            }
            const columns = ['context.columns.pathname', 'context.columns.visitors', 'context.columns.views']
            const query: WebStatsTableQuery = {
                kind: NodeKind.WebStatsTableQuery,
                breakdownBy: WebStatsBreakdown.Page,
                dateRange: { date_from: '-7d' },
                properties: [],
            }

            const result = getWebAnalyticsTableData(response, columns, query)

            expect(result).toEqual([
                ['pathname', 'Visitors', 'Views'],
                ['/home', '', '50'],
            ])
        })
    })

    describe('getWebTrendsTableData', () => {
        it('converts web trends data without comparison', () => {
            const response: WebTrendsQueryResponse = {
                results: [
                    {
                        bucket: '2024-01-01',
                        metrics: {
                            [WebTrendsMetric.UNIQUE_USERS]: 100,
                            [WebTrendsMetric.PAGE_VIEWS]: 250,
                        },
                    },
                    {
                        bucket: '2024-01-02',
                        metrics: {
                            [WebTrendsMetric.UNIQUE_USERS]: 120,
                            [WebTrendsMetric.PAGE_VIEWS]: 300,
                        },
                    },
                ],
            }
            const query: WebTrendsQuery = {
                kind: NodeKind.WebTrendsQuery,
                dateRange: { date_from: '-7d' },
                properties: [],
                compareFilter: { compare: false },
                interval: 'day',
                metrics: [WebTrendsMetric.UNIQUE_USERS, WebTrendsMetric.PAGE_VIEWS],
            }

            const result = getWebTrendsTableData(response, query)

            expect(result).toEqual([
                ['Date', 'Views', 'Visitors'],
                ['2024-01-01', '250', '100'],
                ['2024-01-02', '300', '120'],
            ])
        })

        it('converts web trends data with comparison', () => {
            const response: WebTrendsQueryResponse = {
                results: [
                    {
                        bucket: '2024-01-01',
                        metrics: {
                            [WebTrendsMetric.UNIQUE_USERS]: [100, 90] as any,
                            [WebTrendsMetric.PAGE_VIEWS]: [250, 230] as any,
                        },
                    },
                    {
                        bucket: '2024-01-02',
                        metrics: {
                            [WebTrendsMetric.UNIQUE_USERS]: [120, 110] as any,
                            [WebTrendsMetric.PAGE_VIEWS]: [300, 280] as any,
                        },
                    },
                ],
            }
            const query: WebTrendsQuery = {
                kind: NodeKind.WebTrendsQuery,
                dateRange: { date_from: '-7d' },
                properties: [],
                compareFilter: { compare: true },
                interval: 'day',
                metrics: [WebTrendsMetric.UNIQUE_USERS, WebTrendsMetric.PAGE_VIEWS],
            }

            const result = getWebTrendsTableData(response, query)

            expect(result).toEqual([
                ['Date', 'Views (current)', 'Views (previous)', 'Visitors (current)', 'Visitors (previous)'],
                ['2024-01-01', '250', '230', '100', '90'],
                ['2024-01-02', '300', '280', '120', '110'],
            ])
        })

        it('handles all metric types', () => {
            const response: WebTrendsQueryResponse = {
                results: [
                    {
                        bucket: '2024-01-01',
                        metrics: {
                            [WebTrendsMetric.UNIQUE_USERS]: 100,
                            [WebTrendsMetric.PAGE_VIEWS]: 250,
                            [WebTrendsMetric.SESSIONS]: 80,
                            [WebTrendsMetric.BOUNCES]: 20,
                            [WebTrendsMetric.SESSION_DURATION]: 180,
                            [WebTrendsMetric.TOTAL_SESSIONS]: 80,
                        },
                    },
                ],
            }
            const query: WebTrendsQuery = {
                kind: NodeKind.WebTrendsQuery,
                dateRange: { date_from: '-7d' },
                properties: [],
                interval: 'day',
                metrics: Object.values(WebTrendsMetric),
            }

            const result = getWebTrendsTableData(response, query)

            expect(result[0]).toEqual([
                'Date',
                'Bounces',
                'Views',
                'Session duration',
                'Sessions',
                'Total sessions',
                'Visitors',
            ])
            expect(result[1]).toEqual(['2024-01-01', '20', '250', '180', '80', '80', '100'])
        })

        it('returns empty array for empty results', () => {
            const response: WebTrendsQueryResponse = {
                results: [],
            }
            const query: WebTrendsQuery = {
                kind: NodeKind.WebTrendsQuery,
                dateRange: { date_from: '-7d' },
                properties: [],
                interval: 'day',
                metrics: [WebTrendsMetric.UNIQUE_USERS, WebTrendsMetric.PAGE_VIEWS],
            }

            const result = getWebTrendsTableData(response, query)

            expect(result).toEqual([])
        })

        it('handles null metric values', () => {
            const response: WebTrendsQueryResponse = {
                results: [
                    {
                        bucket: '2024-01-01',
                        metrics: {
                            [WebTrendsMetric.UNIQUE_USERS]: null as any,
                            [WebTrendsMetric.PAGE_VIEWS]: 250,
                        },
                    },
                ],
            }
            const query: WebTrendsQuery = {
                kind: NodeKind.WebTrendsQuery,
                dateRange: { date_from: '-7d' },
                properties: [],
                interval: 'day',
                metrics: [WebTrendsMetric.UNIQUE_USERS, WebTrendsMetric.PAGE_VIEWS],
            }

            const result = getWebTrendsTableData(response, query)

            expect(result).toEqual([
                ['Date', 'Views', 'Visitors'],
                ['2024-01-01', '250', ''],
            ])
        })
    })

    describe('getTrendsTableData', () => {
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

            const result = getTrendsTableData(response)

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

            const result = getTrendsTableData(response)

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

            const result = getTrendsTableData(response)

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

            const result = getTrendsTableData(response)

            expect(result[1]).toEqual(['2024-01-01', '10'])
            expect(result[2]).toEqual(['2024-01-02', '15'])
        })

        it('returns empty array for empty results', () => {
            const response: TrendsQueryResponse = {
                results: [],
            }

            const result = getTrendsTableData(response)

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

            const result = getTrendsTableData(response)

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

            const result = getTrendsTableData(response)

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

            const result = getTrendsTableData(response)

            expect(result[0]).toEqual(['Date', 'Organic Search', 'Unknown', 'Organic Video', 'Direct'])
            expect(result[1]).toEqual(['2024-01-01', '335', '133', '1', '0'])
            expect(result[2]).toEqual(['2024-01-02', '348', '113', '2', '0'])
        })
    })
})
