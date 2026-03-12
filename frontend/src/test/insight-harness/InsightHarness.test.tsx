import { cleanup, waitFor } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { initKeaTests } from '../init'
import {
    breakdown,
    buildTrendsQuery,
    buildTrendsResponse,
    compare,
    dateRange,
    display,
    expectNoNaN,
    filter,
    getChart,
    getQuerySource,
    interval,
    matchTrends,
    renderInsight,
    series,
} from './index'

jest.mock('lib/Chart', () => require('./chartjs-mock').chartJsMock)
jest.mock('chartjs-plugin-crosshair', () => ({}))
jest.mock('chartjs-plugin-annotation', () => ({ default: {} }))
jest.mock('chartjs-plugin-datalabels', () => ({ default: {} }))
jest.mock('chartjs-plugin-stacked100', () => ({ default: {}, __esModule: true }))
jest.mock('chartjs-plugin-trendline', () => ({ default: {} }))
jest.mock('chartjs-adapter-dayjs-3', () => ({}))
jest.mock('torph', () => ({
    TextMorph: ({ children }: { children: string }) => <span>{children}</span>,
}))

Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: jest.fn().mockImplementation((query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addListener: jest.fn(),
        removeListener: jest.fn(),
        addEventListener: jest.fn(),
        removeEventListener: jest.fn(),
        dispatchEvent: jest.fn(),
    })),
})

describe('InsightTestHarness', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/insights/': { results: [] },
                '/api/environments/:team_id/insights/trend': [],
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('renders a basic trends line chart with correct data', async () => {
        renderInsight({
            query: buildTrendsQuery(),
            mockResponses: [matchTrends(buildTrendsResponse([{ label: 'Pageviews', data: [10, 20, 30, 40, 50] }]))],
        })

        await waitFor(() => {
            const chart = getChart()
            expect(chart.datasets).toHaveLength(1)
            expect(chart.datasets[0].label).toBe('Pageviews')
            expect(chart.datasets[0].data).toEqual([10, 20, 30, 40, 50])
            expect(chart.datasets[0][0]).toBe(10)
            expect(chart.datasets[0][4]).toBe(50)
        })

        expectNoNaN()
    })

    it('renders multiple series with indexed access', async () => {
        renderInsight({
            query: buildTrendsQuery({
                series: [
                    { kind: NodeKind.EventsNode, event: '$pageview', name: 'Pageviews' },
                    { kind: NodeKind.EventsNode, event: 'signup', name: 'Signups' },
                ],
            }),
            mockResponses: [
                matchTrends(
                    buildTrendsResponse([
                        { label: 'Pageviews', data: [10, 20, 30] },
                        { label: 'Signups', data: [1, 2, 3] },
                    ])
                ),
            ],
        })

        await waitFor(() => {
            const chart = getChart()
            expect(chart.datasets).toHaveLength(2)
            expect(chart.datasets[0][2]).toBe(30)
            expect(chart.datasets[1][2]).toBe(3)
        })
    })

    it('exposes labels and chart type', async () => {
        renderInsight({
            query: buildTrendsQuery(),
            mockResponses: [
                matchTrends(
                    buildTrendsResponse([{ label: 'Pageviews', data: [10, 20, 30], labels: ['Mon', 'Tue', 'Wed'] }])
                ),
            ],
        })

        await waitFor(() => {
            const chart = getChart()
            expect(chart.labels).toEqual(['Mon', 'Tue', 'Wed'])
            expect(chart.type).toBe('line')
        })
    })

    it('exposes y-axis tick formatting', async () => {
        renderInsight({
            query: buildTrendsQuery(),
            mockResponses: [matchTrends(buildTrendsResponse([{ label: 'Events', data: [100, 200, 300] }]))],
        })

        await waitFor(() => {
            const chart = getChart()
            expect(chart.axes.y.tickLabel(500)).toBeTruthy()
            expect(chart.axes.y.display).toBe(true)
        })
    })

    it('does not produce NaN values for sparse series', async () => {
        renderInsight({
            query: buildTrendsQuery(),
            mockResponses: [matchTrends(buildTrendsResponse([{ label: 'Events', data: [0, 0, 1, 0, 0] }]))],
        })

        await waitFor(() => {
            expect(getChart().datasets[0].data).toEqual([0, 0, 1, 0, 0])
        })

        expectNoNaN()
    })

    describe('interactions', () => {
        it('series.set updates the query source', async () => {
            renderInsight({
                query: buildTrendsQuery(),
                mockResponses: [matchTrends(buildTrendsResponse([{ label: 'Pageviews', data: [10, 20, 30] }]))],
            })

            await waitFor(() => {
                expect(getChart().datasets).toHaveLength(1)
            })

            series.set([
                { event: '$pageview', name: 'Pageviews' },
                { event: 'signup', name: 'Signups' },
            ])

            const source = getQuerySource()
            expect(source.series).toHaveLength(2)
            expect(source.series[0].event).toBe('$pageview')
            expect(source.series[1].event).toBe('signup')
        })

        it('series.add appends to existing series', async () => {
            renderInsight({
                query: buildTrendsQuery(),
                mockResponses: [matchTrends(buildTrendsResponse([{ label: 'Pageviews', data: [10, 20, 30] }]))],
            })

            await waitFor(() => {
                expect(getChart().datasets).toHaveLength(1)
            })

            series.add('signup', { name: 'Signups' })

            const source = getQuerySource()
            expect(source.series).toHaveLength(2)
            expect(source.series[1].event).toBe('signup')
        })

        it('series.remove removes a series by index', async () => {
            renderInsight({
                query: buildTrendsQuery({
                    series: [
                        { kind: NodeKind.EventsNode, event: '$pageview', name: 'Pageviews' },
                        { kind: NodeKind.EventsNode, event: 'signup', name: 'Signups' },
                    ],
                }),
                mockResponses: [
                    matchTrends(
                        buildTrendsResponse([
                            { label: 'Pageviews', data: [10, 20, 30] },
                            { label: 'Signups', data: [1, 2, 3] },
                        ])
                    ),
                ],
            })

            await waitFor(() => {
                expect(getChart().datasets).toHaveLength(2)
            })

            series.remove(0)

            const source = getQuerySource()
            expect(source.series).toHaveLength(1)
            expect(source.series[0].event).toBe('signup')
        })

        it('interval.set updates the interval', async () => {
            renderInsight({
                query: buildTrendsQuery(),
                mockResponses: [matchTrends(buildTrendsResponse([{ label: 'Events', data: [1, 2, 3] }]))],
            })

            await waitFor(() => {
                expect(getChart().datasets).toHaveLength(1)
            })

            interval.set('week')

            expect(getQuerySource().interval).toBe('week')
        })

        it('dateRange.set updates the date range', async () => {
            renderInsight({
                query: buildTrendsQuery(),
                mockResponses: [matchTrends(buildTrendsResponse([{ label: 'Events', data: [1, 2, 3] }]))],
            })

            await waitFor(() => {
                expect(getChart().datasets).toHaveLength(1)
            })

            dateRange.set('-7d', null)

            const source = getQuerySource()
            expect(source.dateRange?.date_from).toBe('-7d')
        })

        it('dateRange.last sets a relative date range', async () => {
            renderInsight({
                query: buildTrendsQuery(),
                mockResponses: [matchTrends(buildTrendsResponse([{ label: 'Events', data: [1, 2, 3] }]))],
            })

            await waitFor(() => {
                expect(getChart().datasets).toHaveLength(1)
            })

            dateRange.last(30, 'd')

            const source = getQuerySource()
            expect(source.dateRange?.date_from).toBe('-30d')
        })

        it('breakdown.set updates the breakdown filter', async () => {
            renderInsight({
                query: buildTrendsQuery(),
                mockResponses: [matchTrends(buildTrendsResponse([{ label: 'Events', data: [1, 2, 3] }]))],
            })

            await waitFor(() => {
                expect(getChart().datasets).toHaveLength(1)
            })

            breakdown.set('$browser')

            const source = getQuerySource()
            expect(source.breakdownFilter?.breakdown).toBe('$browser')
            expect(source.breakdownFilter?.breakdown_type).toBe('event')
        })

        it('breakdown.clear removes the breakdown', async () => {
            renderInsight({
                query: buildTrendsQuery(),
                mockResponses: [matchTrends(buildTrendsResponse([{ label: 'Events', data: [1, 2, 3] }]))],
            })

            await waitFor(() => {
                expect(getChart().datasets).toHaveLength(1)
            })

            breakdown.set('$browser')
            breakdown.clear()

            const source = getQuerySource()
            expect(source.breakdownFilter?.breakdown).toBeUndefined()
        })

        it('display.set changes the chart display type', async () => {
            renderInsight({
                query: buildTrendsQuery(),
                mockResponses: [matchTrends(buildTrendsResponse([{ label: 'Events', data: [1, 2, 3] }]))],
            })

            await waitFor(() => {
                expect(getChart().datasets).toHaveLength(1)
            })

            display.set(ChartDisplayType.ActionsBar)

            const source = getQuerySource()
            expect(source.trendsFilter?.display).toBe(ChartDisplayType.ActionsBar)
        })

        it('compare.enable and compare.disable toggle comparison', async () => {
            renderInsight({
                query: buildTrendsQuery(),
                mockResponses: [matchTrends(buildTrendsResponse([{ label: 'Events', data: [1, 2, 3] }]))],
            })

            await waitFor(() => {
                expect(getChart().datasets).toHaveLength(1)
            })

            compare.enable()
            expect(getQuerySource().compareFilter?.compare).toBe(true)

            compare.disable()
            expect(getQuerySource().compareFilter?.compare).toBe(false)
        })

        it('filter.setTestAccountsFilter updates the filter', async () => {
            renderInsight({
                query: buildTrendsQuery(),
                mockResponses: [matchTrends(buildTrendsResponse([{ label: 'Events', data: [1, 2, 3] }]))],
            })

            await waitFor(() => {
                expect(getChart().datasets).toHaveLength(1)
            })

            filter.setTestAccountsFilter(true)

            expect(getQuerySource().filterTestAccounts).toBe(true)
        })

        it('interaction triggers re-render with updated data', async () => {
            let requestCount = 0
            renderInsight({
                query: buildTrendsQuery(),
                mockResponses: [
                    {
                        match: (query) => {
                            if (query.kind !== NodeKind.TrendsQuery) {
                                return false
                            }
                            requestCount++
                            return true
                        },
                        response: buildTrendsResponse([{ label: 'Events', data: [5, 10, 15] }]),
                    },
                ],
            })

            await waitFor(() => {
                expect(getChart().datasets).toHaveLength(1)
            })

            const initialRequests = requestCount

            interval.set('week')

            await waitFor(() => {
                expect(requestCount).toBeGreaterThan(initialRequests)
            })
        })
    })
})
