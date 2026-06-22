import type { ChartTheme, Series } from '../../core/types'
import { ReferenceLine } from '../../overlays/ReferenceLine'
import { renderHogChart } from '../../testing'
import { ComboChart } from './ComboChart'

const THEME: ChartTheme = {
    colors: ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728'],
    backgroundColor: '#ffffff',
    gridColor: '#eeeeee',
    crosshairColor: '#888888',
}

const LABELS = ['Mon', 'Tue', 'Wed']

const BAR_AND_LINE: Series[] = [
    { key: 'visits', label: 'Visits', data: [40, 60, 50], type: 'bar' },
    { key: 'avg', label: 'Avg', data: [42, 55, 53], type: 'line' },
]

describe('ComboChart', () => {
    it('renders a bar + line combo without crashing', () => {
        const { chart } = renderHogChart(<ComboChart series={BAR_AND_LINE} labels={LABELS} theme={THEME} />)
        expect(chart.seriesCount).toBe(2)
        expect(chart.yTicks().length).toBeGreaterThan(0)
    })

    it('renders an area + line combo without crashing', () => {
        const series: Series[] = [
            { key: 'area', label: 'Area', data: [10, 30, 20], type: 'area' },
            { key: 'avg', label: 'Avg', data: [15, 25, 20], type: 'line' },
        ]
        const { chart } = renderHogChart(<ComboChart series={series} labels={LABELS} theme={THEME} />)
        expect(chart.seriesCount).toBe(2)
    })

    it('renders empty state without crashing', () => {
        const { chart } = renderHogChart(<ComboChart series={[]} labels={[]} theme={THEME} />)
        expect(chart.seriesCount).toBe(0)
    })

    it('forwards `dataAttr` to the chart wrapper', () => {
        const { chart } = renderHogChart(
            <ComboChart series={BAR_AND_LINE} labels={LABELS} theme={THEME} dataAttr="combo-instance" />
        )
        expect(chart.element.getAttribute('data-attr')).toBe('combo-instance')
    })

    it('applies xTickFormatter to x-axis ticks', () => {
        const { chart } = renderHogChart(
            <ComboChart
                series={BAR_AND_LINE}
                labels={LABELS}
                theme={THEME}
                config={{ xTickFormatter: (_l, i) => `tick-${i}` }}
            />
        )
        expect(chart.xTicks()).toEqual(['tick-0', 'tick-1', 'tick-2'])
    })

    it('renders a right axis when a series sets yAxisId: right', () => {
        const series: Series[] = [
            { key: 'b', label: 'B', data: [40, 60, 50], type: 'bar' },
            { key: 'l', label: 'L', data: [1000, 2000, 3000], type: 'line', yAxisId: 'right' },
        ]
        const { chart } = renderHogChart(<ComboChart series={series} labels={LABELS} theme={THEME} />)
        expect(chart.hasRightAxis).toBe(true)
        expect(chart.yRightTicks().length).toBeGreaterThan(0)
    })

    describe('hover & tooltip', () => {
        it('lists every visible series at the hovered x', async () => {
            const { chart } = renderHogChart(<ComboChart series={BAR_AND_LINE} labels={LABELS} theme={THEME} />)
            chart.hoverAtIndex(1)
            const tooltip = await chart.waitForTooltip()
            const keys = tooltip.seriesData.map((s) => s.series.key).sort()
            expect(keys).toEqual(['avg', 'visits'])
        })

        it('keeps line series in tooltip even when the cursor is in a band gap', async () => {
            const onlyLine: Series[] = [
                { key: 'b', label: 'B', data: [10, 20, 30], type: 'bar' },
                { key: 'l', label: 'L', data: [5, 15, 25], type: 'line' },
            ]
            const { chart } = renderHogChart(<ComboChart series={onlyLine} labels={LABELS} theme={THEME} />)
            chart.hoverAtIndex(1)
            const tooltip = await chart.waitForTooltip()
            const keys = tooltip.seriesData.map((s) => s.series.key)
            expect(keys).toContain('l')
        })

        it('renders bar+line on dual axes and shows both in the tooltip', async () => {
            const series: Series[] = [
                { key: 'b', label: 'Revenue', data: [1000, 2000, 1500], type: 'bar' },
                { key: 'l', label: 'Conv', data: [0.02, 0.03, 0.025], type: 'line', yAxisId: 'right' },
            ]
            const { chart } = renderHogChart(<ComboChart series={series} labels={LABELS} theme={THEME} />)
            chart.hoverAtIndex(1)
            const tooltip = await chart.waitForTooltip()
            expect(tooltip.seriesData.map((s) => s.series.key).sort()).toEqual(['b', 'l'])
            expect(chart.hasRightAxis).toBe(true)
        })

        it('pins the tooltip on click when tooltip.pinnable is true', async () => {
            const { chart } = renderHogChart(
                <ComboChart
                    series={BAR_AND_LINE}
                    labels={LABELS}
                    theme={THEME}
                    config={{ tooltip: { pinnable: true } }}
                />
            )
            await chart.clickAtIndex(1)
            const tooltip = await chart.waitForTooltip()
            expect(tooltip.isPinned).toBe(true)
        })

        it('stacked bar tooltip shows each bar segment own value, not the cumulative total', async () => {
            // Two bar series stacked: a=20 + b=15 at index 1. b's stacked top is 35, but the
            // tooltip must report b's own 15.
            const series: Series[] = [
                { key: 'a', label: 'A', data: [10, 20, 30], type: 'bar' },
                { key: 'b', label: 'B', data: [5, 15, 25], type: 'bar' },
                { key: 'l', label: 'L', data: [50, 60, 70], type: 'line' },
            ]
            const { chart } = renderHogChart(
                <ComboChart series={series} labels={LABELS} theme={THEME} config={{ barLayout: 'stacked' }} />
            )
            chart.hoverAtIndex(1)
            const tooltip = await chart.waitForTooltip()
            expect(tooltip.series.a.value).toBe(20)
            expect(tooltip.series.b.value).toBe(15)
            expect(tooltip.series.l.value).toBe(60)
        })
    })

    describe('children & error boundary', () => {
        it('renders a ReferenceLine child via the accessor', () => {
            const { chart } = renderHogChart(
                <ComboChart series={BAR_AND_LINE} labels={LABELS} theme={THEME}>
                    <ReferenceLine value={45} label="Target" />
                </ComboChart>
            )
            const lines = chart.referenceLines()
            expect(lines).toHaveLength(1)
            expect(lines[0].label).toBe('Target')
        })

        it('reports render errors through onError', () => {
            const onError = jest.fn()
            const tooltip = (): never => {
                throw new Error('boom')
            }
            // ChartErrorBoundary surfaces the error to onError; React still logs it. Restore
            // explicitly rather than via afterEach — setupJsdom installs a persistent
            // getBoundingClientRect spy that restoreAllMocks would also tear down.
            const consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {})
            try {
                const { chart } = renderHogChart(
                    <ComboChart
                        series={BAR_AND_LINE}
                        labels={LABELS}
                        theme={THEME}
                        tooltip={tooltip}
                        onError={onError}
                    />
                )
                chart.hoverAtIndex(1)
                expect(onError).toHaveBeenCalledWith(expect.objectContaining({ message: 'boom' }), expect.anything())
            } finally {
                consoleErrorSpy.mockRestore()
            }
        })
    })
})
