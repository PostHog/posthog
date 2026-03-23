import { cleanup } from '@testing-library/react'

import { NodeKind, TrendsQueryResponse } from '~/queries/schema/schema-general'
import {
    buildTrendsQuery,
    type MockResponse,
    type QueryBody,
    renderInsightPage,
    waitForChart,
} from '~/test/insight-testing'
import { ChartDisplayType } from '~/types'

jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
}))

// Current period: Jun 10-14, Previous period: Jun 3-7
// Deliberately different date ranges so we can detect which one is used for x-axis labels
const CURRENT_DAYS = ['2024-06-10', '2024-06-11', '2024-06-12', '2024-06-13', '2024-06-14']
const PREVIOUS_DAYS = ['2024-06-03', '2024-06-04', '2024-06-05', '2024-06-06', '2024-06-07']

function compareResponse(): TrendsQueryResponse {
    return {
        results: [
            {
                action: { id: '$pageview', type: 'events', name: '$pageview' },
                label: '$pageview',
                count: 100,
                data: [10, 20, 30, 25, 15],
                labels: ['10-Jun-2024', '11-Jun-2024', '12-Jun-2024', '13-Jun-2024', '14-Jun-2024'],
                days: CURRENT_DAYS,
                compare: true,
                compare_label: 'current',
            },
            {
                action: { id: '$pageview', type: 'events', name: '$pageview' },
                label: '$pageview',
                count: 80,
                data: [8, 15, 25, 20, 12],
                labels: ['3-Jun-2024', '4-Jun-2024', '5-Jun-2024', '6-Jun-2024', '7-Jun-2024'],
                days: PREVIOUS_DAYS,
                compare: true,
                compare_label: 'previous',
            },
        ],
    } as TrendsQueryResponse
}

const compareMock: MockResponse = {
    match: (query: QueryBody) => query.kind === NodeKind.TrendsQuery,
    response: compareResponse,
}

describe('LineGraph', () => {
    afterEach(cleanup)

    describe('Incomplete current day', () => {
        beforeEach(() => {
            // Set "now" to midday on the last day of the default test data (Mon-Fri, Jun 10-14 2024)
            jest.useFakeTimers({ advanceTimers: true })
            jest.setSystemTime(new Date('2024-06-14T12:00:00Z'))
        })

        afterEach(() => {
            jest.useRealTimers()
        })

        it('renders the last data point with a dashed line when it falls on the current day', async () => {
            renderInsightPage({
                query: buildTrendsQuery(),
            })

            const chart = await waitForChart()
            const dataset = chart.config.data?.datasets?.[0]
            const borderDashFn = (dataset as any)?.segment?.borderDash

            expect(typeof borderDashFn).toBe('function')

            // Thu (index 3) is in the past — should be solid (no dash)
            expect(borderDashFn({ p1DataIndex: 3 })).toBeUndefined()

            // Fri (index 4) is "today" — should be dashed
            expect(borderDashFn({ p1DataIndex: 4 })).toEqual([10, 10])
        })

        it('does not render dashed lines when all data is from past days', async () => {
            // Move "now" to the day after the data range
            jest.setSystemTime(new Date('2024-06-15T12:00:00Z'))

            renderInsightPage({
                query: buildTrendsQuery(),
            })

            const chart = await waitForChart()
            const dataset = chart.config.data?.datasets?.[0]
            const borderDashFn = (dataset as any)?.segment?.borderDash

            // No incomplete points — borderDash should not be a function
            expect(borderDashFn).toBeUndefined()
        })

        it('excludes incomplete day from trend line regression', async () => {
            renderInsightPage({
                query: buildTrendsQuery({
                    trendsFilter: { showTrendLines: true },
                }),
            })

            const chart = await waitForChart()
            const dataset = chart.config.data?.datasets?.[0] as any

            // The trendline config should exclude the incomplete last point
            expect(dataset.trendlineLinear).toBeTruthy()
            expect(dataset.trendlineLinear.trendoffset).toBe(-1)
        })

        it('does not set trendoffset when all data is complete', async () => {
            jest.setSystemTime(new Date('2024-06-15T12:00:00Z'))

            renderInsightPage({
                query: buildTrendsQuery({
                    trendsFilter: { showTrendLines: true },
                }),
            })

            const chart = await waitForChart()
            const dataset = chart.config.data?.datasets?.[0] as any

            // No incomplete points — trendoffset should be 0
            expect(dataset.trendlineLinear).toBeTruthy()
            expect(dataset.trendlineLinear.trendoffset).toBe(0)
        })
    })

    describe('Compare to previous', () => {
        it('uses current period dates on x-axis for unstacked bar chart with compare', async () => {
            renderInsightPage({
                query: buildTrendsQuery({
                    trendsFilter: { display: ChartDisplayType.ActionsUnstackedBar },
                    compareFilter: { compare: true },
                }),
                mocks: { mockResponses: [compareMock] },
            })

            const chart = await waitForChart()

            // trendsDataLogic sorts "previous" first for unstacked bar charts
            expect(chart.series(0).compareLabel).toBe('previous')

            const firstTickLabel = chart.axes.x.tickLabel(0)
            expect(firstTickLabel).toBe('Jun 10')
        })
    })
})
