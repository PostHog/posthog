import { cleanup } from '@testing-library/react'

import { ChartEvent, InteractionItem } from 'lib/Chart'

import { GraphDataset, GraphPointPayload } from '~/types'

import { onChartClick } from './LineGraph'

describe('LineGraph', () => {
    afterEach(cleanup)

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
