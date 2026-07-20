import type { ChartTheme } from '../../core/types'
import { renderHogChart } from '../../testing'
import { Heatmap } from './Heatmap'

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
})
