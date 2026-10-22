import { waitFor } from '@testing-library/react'

import type { ChartTheme } from '../../core/types'
import { rawDrag, renderHogChart } from '../../testing'
import { Heatmap, type HeatmapBrushData, type HeatmapCellDatum, type HeatmapCellStyle } from './Heatmap'

const THEME: ChartTheme = {
    colors: ['#1f77b4', '#ff7f0e'],
    backgroundColor: '#ffffff',
    // Light, as a dark theme sets it, so a label that borrows axis ink fails the contrast test.
    axisColor: '#cccccc',
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
        const { chart } = renderHogChart(<Heatmap xLabels={X_LABELS} yLabels={Y_LABELS} cells={CELLS} theme={THEME} />)
        expect(chart.seriesCount).toBe(Y_LABELS.length)
    })

    // The categorical y-axis rides the numeric tick machinery (row-center values + a formatter
    // mapping back to labels). If that adapter breaks, ticks render as raw numbers like "0.5".
    it('renders row labels, not row-unit numbers, as y-axis ticks', () => {
        const { chart } = renderHogChart(<Heatmap xLabels={X_LABELS} yLabels={Y_LABELS} cells={CELLS} theme={THEME} />)
        const ticks = chart.yTicks()
        expect(ticks.length).toBeGreaterThan(0)
        for (const tick of ticks) {
            expect(Y_LABELS).toContain(tick)
        }
    })

    it('renders column labels as x-axis ticks', () => {
        const { chart } = renderHogChart(<Heatmap xLabels={X_LABELS} yLabels={Y_LABELS} cells={CELLS} theme={THEME} />)
        const ticks = chart.xTicks()
        expect(ticks.length).toBeGreaterThan(0)
        for (const tick of ticks) {
            expect(X_LABELS).toContain(tick)
        }
    })

    it('keeps columns with the same label distinct', () => {
        // Columns are keyed by index, not label text; keying by label would collapse the two
        // "10:00" columns onto one x position, dropping a tick and misrouting hover/click.
        const dupLabels = ['10:00', '10:00', '10:02', '10:04']
        const { chart } = renderHogChart(<Heatmap xLabels={dupLabels} yLabels={Y_LABELS} cells={CELLS} theme={THEME} />)
        expect(chart.xTicks()).toEqual(dupLabels)
    })

    it('tolerates a ragged cells grid without crashing', () => {
        const { chart } = renderHogChart(
            <Heatmap xLabels={X_LABELS} yLabels={Y_LABELS} cells={[[1], [2, 3]]} theme={THEME} />
        )
        expect(chart.seriesCount).toBe(Y_LABELS.length)
    })

    describe('cellLabel', () => {
        function cellLabels(element: HTMLElement): HTMLElement[] {
            return Array.from(element.querySelectorAll('[data-attr="hog-chart-heatmap-cell-label"]'))
        }

        function renderLabelled(
            cellLabel: (cell: HeatmapCellDatum) => string | null,
            xLabels: string[] = X_LABELS,
            cells: number[][] = CELLS
        ): HTMLElement[] {
            const { chart } = renderHogChart(
                <Heatmap xLabels={xLabels} yLabels={Y_LABELS} cells={cells} theme={THEME} config={{ cellLabel }} />
            )
            return cellLabels(chart.element)
        }

        it('renders no labels without a formatter', () => {
            const { chart } = renderHogChart(
                <Heatmap xLabels={X_LABELS} yLabels={Y_LABELS} cells={CELLS} theme={THEME} />
            )
            expect(cellLabels(chart.element)).toHaveLength(0)
        })

        it('labels every cell, empty ones included', () => {
            const labels = renderLabelled((cell) => (cell.value > 0 ? String(cell.value) : '-'))
            expect(labels).toHaveLength(X_LABELS.length * Y_LABELS.length)
            expect(labels.filter((el) => el.textContent === '-')).toHaveLength(8)
        })

        it('leaves a cell unlabelled when the formatter returns null', () => {
            const labels = renderLabelled((cell) => (cell.value > 0 ? String(cell.value) : null))
            expect(labels).toHaveLength(8)
        })

        // Without the fit check a dense grid prints every number on top of its neighbour.
        it('drops labels too wide for their cell', () => {
            const manyColumns = Array.from({ length: 60 }, (_, i) => `col-${i}`)
            const wideCells = Y_LABELS.map(() => manyColumns.map(() => 5))
            expect(renderLabelled(() => '100.0%', manyColumns, wideCells)).toHaveLength(0)
        })

        // The densest cells are painted at the full accent, where dark text is unreadable.
        it('turns the label white over a saturated cell and keeps it dark over an empty one', () => {
            const labels = renderLabelled((cell) => String(cell.value))
            const byText = new Map(labels.map((el) => [el.textContent, el.style.color]))
            expect(byText.get('10')).toBe('rgb(255, 255, 255)')
            expect(byText.get('0')).toBe('rgb(17, 17, 17)')
        })
    })

    // Both cases guard the label's contrast step against the cell's real fill. Reading the chart
    // accent instead would print white text on a pale cell and dark text on an unfilled one.
    describe('cellStyle', () => {
        function labelColor(cellStyle: (cell: HeatmapCellDatum) => HeatmapCellStyle | null): string {
            const { chart } = renderHogChart(
                <Heatmap
                    xLabels={X_LABELS}
                    yLabels={Y_LABELS}
                    cells={CELLS}
                    theme={THEME}
                    config={{ cellLabel: (cell) => String(cell.value), cellStyle }}
                />
            )
            const labels = Array.from(
                chart.element.querySelectorAll<HTMLElement>('[data-attr="hog-chart-heatmap-cell-label"]')
            )
            return labels.find((el) => el.textContent === '10')?.style.color ?? ''
        }

        // THEME sets no axisColor, so a dark label falls back to #111111.
        const DARK_TEXT = 'rgb(17, 17, 17)'

        it('contrasts the label against a per-cell accent', () => {
            expect(labelColor(() => ({ color: '#ffffcc' }))).toBe(DARK_TEXT)
        })

        it('contrasts the label against the background on an outlined cell', () => {
            expect(labelColor(() => ({ outlined: true }))).toBe(DARK_TEXT)
        })

        // A retention cohort at 0% is a real value, and must not look like a cell past its end.
        it.each([
            { filled: false, fills: 0 },
            { filled: true, fills: X_LABELS.length * Y_LABELS.length },
        ])('paints $fills fills on an all-zero grid when filled is $filled', async ({ filled, fills }) => {
            const zeros = Y_LABELS.map(() => X_LABELS.map(() => 0))
            const { chart } = renderHogChart(
                <Heatmap
                    xLabels={X_LABELS}
                    yLabels={Y_LABELS}
                    cells={zeros}
                    theme={THEME}
                    config={{ cellStyle: () => ({ filled }) }}
                />
            )
            const ctx = chart.element.querySelector('canvas')!.getContext('2d') as unknown as {
                __getDrawCalls: () => { type: string }[]
            }
            await waitFor(() => expect(ctx.__getDrawCalls().some((call) => call.type === 'clearRect')).toBe(true))
            expect(ctx.__getDrawCalls().filter((call) => call.type === 'fillRect')).toHaveLength(fills)
        })
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
