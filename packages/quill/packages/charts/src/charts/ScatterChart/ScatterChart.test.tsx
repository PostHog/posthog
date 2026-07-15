import type { ChartTheme } from '../../core/types'
import { hoverAtIndex, renderHogChart, waitForHogChartTooltip } from '../../testing'
import { ScatterChart, type ScatterChartConfig, type ScatterChartPoint } from './ScatterChart'

const THEME: ChartTheme = {
    colors: ['#1f77b4', '#ff7f0e', '#2ca02c'],
    backgroundColor: '#ffffff',
    gridColor: '#eeeeee',
    crosshairColor: '#888888',
}

const POINTS: ScatterChartPoint[] = [
    { x: 30, y: 1, label: 'C' },
    { x: 10, y: 2, label: 'A' },
    { x: 20, y: 3, label: 'B' },
]

const LOG_POINTS: ScatterChartPoint[] = [
    { x: 10, y: 100 },
    { x: 100, y: 10 },
    { x: 1000, y: 1000 },
]

const SINGLE_POINT: ScatterChartPoint[] = [{ x: 42, y: 17, label: 'Only' }]

describe('ScatterChart', () => {
    it.each<[string, ScatterChartPoint[], ScatterChartConfig | undefined]>([
        ['linear', POINTS, undefined],
        ['log scale', LOG_POINTS, { xLogScale: true, yLogScale: true }],
        ['single point', SINGLE_POINT, undefined],
    ])('renders %s without throwing', (_, points, config) => {
        const { chart } = renderHogChart(<ScatterChart points={points} theme={THEME} config={config} />)
        expect(chart.seriesCount).toBeGreaterThan(0)
    })

    it('renders empty state without crashing', () => {
        const { chart } = renderHogChart(<ScatterChart points={[]} theme={THEME} />)
        expect(chart.seriesCount).toBe(0)
    })

    it('sorts points by x so a hover on the left resolves to the smallest-x point', async () => {
        // Points arrive unsorted; the x-bisector hit-test needs ascending x. A left-edge hover must
        // resolve to the smallest-x point ('A'), not the first point as supplied ('B').
        const points: ScatterChartPoint[] = [
            { x: 90, y: 1, label: 'B' },
            { x: 10, y: 2, label: 'A' },
        ]
        const { chart } = renderHogChart(<ScatterChart points={points} theme={THEME} />, { nativeTooltip: true })
        hoverAtIndex(chart.element, 0, points.length)
        const tooltip = await waitForHogChartTooltip()
        expect(tooltip.textContent).toContain('A')
        expect(tooltip.textContent).not.toContain('B')
    })

    it('shows the exact xDisplay in the tooltip when provided', async () => {
        // A single point removes hover ambiguity; the tooltip must show the exact large-int digits
        // rather than the rounded Number() form.
        // x is the value Number() rounds 9007199254740993 to; xDisplay carries the exact digits.
        const points: ScatterChartPoint[] = [{ x: 9007199254740992, y: 5, label: 'Big', xDisplay: '9007199254740993' }]
        const { chart } = renderHogChart(<ScatterChart points={points} theme={THEME} />, { nativeTooltip: true })
        hoverAtIndex(chart.element, 0, points.length)
        const tooltip = await waitForHogChartTooltip()
        expect(tooltip.textContent).toContain('9007199254740993')
    })

    it('forwards dataAttr to the chart wrapper', () => {
        const { chart } = renderHogChart(<ScatterChart points={POINTS} theme={THEME} dataAttr="scatter-instance" />)
        expect(chart.element.getAttribute('data-attr')).toBe('scatter-instance')
    })
})
