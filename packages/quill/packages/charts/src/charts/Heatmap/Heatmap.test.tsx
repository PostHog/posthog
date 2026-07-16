import { waitFor } from '@testing-library/react'

import type { ChartTheme } from '../../core/types'
import { rawDrag, renderHogChart } from '../../testing'
import { Heatmap, type HeatmapBrushData } from './Heatmap'

const THEME: ChartTheme = {
    colors: ['#1f77b4', '#ff7f0e'],
    backgroundColor: '#ffffff',
    gridColor: '#eeeeee',
    crosshairColor: '#888888',
}

const X_LABELS = ['10:00', '10:02', '10:04', '10:06']
const Y_LABELS = ['1ms', '2ms', '5ms', '10ms']
const CELLS = [
    [3, 0, 1, 0],
    [10, 4, 0, 2],
    [0, 1, 6, 0],
    [0, 0, 0, 1],
]

describe('Heatmap', () => {
    it('renders one adapter series per row', () => {
        const { chart } = renderHogChart(
            <Heatmap xLabels={X_LABELS} yLabels={Y_LABELS} cells={CELLS} theme={THEME} />
        )
        expect(chart.seriesCount).toBe(Y_LABELS.length)
    })

    // The categorical y-axis rides the numeric tick machinery (row-center values + a formatter
    // mapping back to labels). If that adapter breaks, ticks render as raw numbers like "0.5".
    it('renders row labels, not row-unit numbers, as y-axis ticks', () => {
        const { chart } = renderHogChart(
            <Heatmap xLabels={X_LABELS} yLabels={Y_LABELS} cells={CELLS} theme={THEME} />
        )
        const ticks = chart.yTicks()
        expect(ticks.length).toBeGreaterThan(0)
        for (const tick of ticks) {
            expect(Y_LABELS).toContain(tick)
        }
    })

    it('renders column labels as x-axis ticks', () => {
        const { chart } = renderHogChart(
            <Heatmap xLabels={X_LABELS} yLabels={Y_LABELS} cells={CELLS} theme={THEME} />
        )
        const ticks = chart.xTicks()
        expect(ticks.length).toBeGreaterThan(0)
        for (const tick of ticks) {
            expect(X_LABELS).toContain(tick)
        }
    })

    it('tolerates a ragged cells grid without crashing', () => {
        const { chart } = renderHogChart(
            <Heatmap xLabels={X_LABELS} yLabels={Y_LABELS} cells={[[1], [2, 3]]} theme={THEME} />
        )
        expect(chart.seriesCount).toBe(Y_LABELS.length)
    })

    // The jsdom chart mounts at 800x400; coordinates well inside the plot area are safe for drags.
    describe('onBrush', () => {
        async function brush(from: { x: number; y: number }, to: { x: number; y: number }): Promise<HeatmapBrushData> {
            const onBrush = jest.fn()
            const { chart } = renderHogChart(
                <Heatmap xLabels={X_LABELS} yLabels={Y_LABELS} cells={CELLS} theme={THEME} onBrush={onBrush} />
            )
            // The chart commits scales in a post-render effect; retry the drag until it lands.
            await waitFor(() => {
                rawDrag(chart.element, { from, to })
                expect(onBrush).toHaveBeenCalled()
            })
            return onBrush.mock.calls[onBrush.mock.calls.length - 1][0]
        }

        it('reports ordered in-bounds column and row ranges for a diagonal drag', async () => {
            const sel = await brush({ x: 200, y: 300 }, { x: 600, y: 120 })
            expect(sel.x.startIndex).toBeLessThanOrEqual(sel.x.endIndex)
            expect(sel.x.startIndex).toBeGreaterThanOrEqual(0)
            expect(sel.x.endIndex).toBeLessThan(X_LABELS.length)
            expect(sel.y.startIndex).toBeLessThanOrEqual(sel.y.endIndex)
            expect(sel.y.startIndex).toBeGreaterThanOrEqual(0)
            expect(sel.y.endIndex).toBeLessThan(Y_LABELS.length)
            // A drag that stops short of the plot top must NOT reach the top row — rows are
            // resolved bottom-up from the pixel range, not defaulted to full height.
            expect(sel.y.endIndex).toBeLessThan(Y_LABELS.length - 1)
        })

        it('spans every row for a near-horizontal drag (time-range selection)', async () => {
            const sel = await brush({ x: 200, y: 200 }, { x: 600, y: 203 })
            expect(sel.y).toEqual({ startIndex: 0, endIndex: Y_LABELS.length - 1 })
        })
    })
})
