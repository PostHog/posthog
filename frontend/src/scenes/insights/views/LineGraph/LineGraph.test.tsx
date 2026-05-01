import { cleanup } from '@testing-library/react'

import { ChartEvent, InteractionItem } from 'lib/Chart'

import { NodeKind, TrendsQueryResponse } from '~/queries/schema/schema-general'
import {
    buildTrendsQuery,
    type MockResponse,
    type QueryBody,
    renderInsight,
    waitForChart,
} from '~/test/insight-testing'
import { ChartDisplayType, GraphDataset, GraphPointPayload } from '~/types'

import { onChartClick } from './LineGraph'

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
            renderInsight({
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

            renderInsight({
                query: buildTrendsQuery(),
            })

            const chart = await waitForChart()
            const dataset = chart.config.data?.datasets?.[0]
            const borderDashFn = (dataset as any)?.segment?.borderDash

            // No incomplete points — borderDash should not be a function
            expect(borderDashFn).toBeUndefined()
        })

        it('excludes incomplete day from trend line regression', async () => {
            renderInsight({
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

            renderInsight({
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
            renderInsight({
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

    describe('onChartClick', () => {
        // Stacked bar geometry (canvas coords, y=0 at top):
        //   Email (dataset 2):      top=50,  base=150, center=100
        //   Flutter (dataset 1):    top=150, base=250, center=200
        //   Webapp DAU (dataset 0): top=250, base=350, center=300
        const datasets: GraphDataset[] = [
            { id: 0, label: 'Webapp DAU', data: [100], action: { order: 0 } } as GraphDataset,
            { id: 1, label: 'Flutter', data: [100], action: { order: 1 } } as GraphDataset,
            { id: 2, label: 'Email', data: [100], action: { order: 2 } } as GraphDataset,
        ]

        const barElements = [
            { y: 250, base: 350, x: 100 }, // Webapp DAU (bottom of stack)
            { y: 150, base: 250, x: 100 }, // Flutter (middle)
            { y: 50, base: 150, x: 100 }, // Email (top)
        ]

        function makeIndexElements(): InteractionItem[] {
            return barElements.map((el, i) => ({
                element: el as any,
                datasetIndex: i,
                index: 0,
            }))
        }

        function makeMockChart(
            pointHits: InteractionItem[] = [],
            tooltipDataPoints?: { datasetIndex: number; dataIndex: number }[]
        ): any {
            return {
                getElementsAtEventForMode: (_event: Event, mode: string) => {
                    if (mode === 'point') {
                        return pointHits
                    }
                    return makeIndexElements()
                },
                tooltip: tooltipDataPoints ? { dataPoints: tooltipDataPoints } : undefined,
            }
        }

        function makeEvent(y: number): ChartEvent {
            return {
                type: 'click',
                native: new MouseEvent('click'),
                x: 100,
                y,
            }
        }

        function clickAndCapture(chart: any, event: ChartEvent): GraphPointPayload | undefined {
            let captured: GraphPointPayload | undefined
            onChartClick(event, chart, datasets, (payload) => {
                captured = payload
            })
            return captured
        }

        it.each([
            ['below center (y=220)', 220],
            ['above center (y=180)', 180],
        ])('selects Flutter when clicking %s in a stacked bar chart', (_, y) => {
            const chart = makeMockChart()
            const payload = clickAndCapture(chart, makeEvent(y as number))

            expect(payload).toBeTruthy()
            expect(payload!.points.referencePoint.dataset.label).toBe('Flutter')
            expect(payload!.points.referencePoint.datasetIndex).toBe(1)
        })

        it('selects the correct series when pointsIntersectingClick has a direct hit', () => {
            const directHit: InteractionItem[] = [{ element: barElements[1] as any, datasetIndex: 1, index: 0 }]
            const chart = makeMockChart(directHit)
            const payload = clickAndCapture(chart, makeEvent(200))

            expect(payload).toBeTruthy()
            expect(payload!.points.referencePoint.dataset.label).toBe('Flutter')
            expect(payload!.points.clickedPointNotLine).toBe(true)
        })

        it('uses tooltip reference point over click detection to match what user sees', () => {
            // Tooltip says Flutter but click detection hits Email — tooltip should win
            const directHit: InteractionItem[] = [{ element: barElements[2] as any, datasetIndex: 2, index: 0 }]
            const tooltipDataPoints = [{ datasetIndex: 1, dataIndex: 0 }]
            const chart = makeMockChart(directHit, tooltipDataPoints)
            const payload = clickAndCapture(chart, makeEvent(200))

            expect(payload).toBeTruthy()
            expect(payload!.points.referencePoint.dataset.label).toBe('Flutter')
            expect(payload!.points.referencePoint.datasetIndex).toBe(1)
        })

        it('falls back to click detection when no tooltip is active', () => {
            const chart = makeMockChart([], undefined)
            const payload = clickAndCapture(chart, makeEvent(200))

            expect(payload).toBeTruthy()
            expect(payload!.points.referencePoint.dataset.label).toBe('Flutter')
        })

        it('ignores stale tooltip pointing to a different column than the click', () => {
            // Tooltip cached from hovering a different data index (index=5) — should be ignored
            const tooltipDataPoints = [{ datasetIndex: 1, dataIndex: 5 }]
            const chart = makeMockChart([], tooltipDataPoints)
            const payload = clickAndCapture(chart, makeEvent(200))

            expect(payload).toBeTruthy()
            // Falls back to click detection since tooltip column doesn't match
            expect(payload!.points.referencePoint.dataset.label).toBe('Flutter')
        })

        it('works correctly for line charts where elements have no base property', () => {
            const lineDatasets: GraphDataset[] = [
                { id: 0, label: 'Series A', data: [50], action: { order: 0 } } as GraphDataset,
                { id: 1, label: 'Series B', data: [80], action: { order: 1 } } as GraphDataset,
            ]
            const lineElements = [
                { y: 200, x: 100 }, // Series A
                { y: 100, x: 100 }, // Series B (higher value = lower y)
            ]
            const chart = {
                getElementsAtEventForMode: (_event: Event, mode: string) => {
                    if (mode === 'point') {
                        return []
                    }
                    return lineElements.map((el, i) => ({
                        element: el as any,
                        datasetIndex: i,
                        index: 0,
                    }))
                },
            }

            // Click at y=110, closer to Series B (y=100)
            let captured: GraphPointPayload | undefined
            onChartClick(makeEvent(110), chart as any, lineDatasets, (payload) => {
                captured = payload
            })

            expect(captured).toBeTruthy()
            expect(captured!.points.referencePoint.dataset.label).toBe('Series B')
        })
    })
})
