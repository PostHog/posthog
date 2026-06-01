import { cleanup, waitFor } from '@testing-library/react'

import type { ChartTheme, Series, TooltipContext } from '../core/types'
import { ReferenceLine } from '../overlays/ReferenceLine'
import {
    clickAtIndex,
    getHogChartTooltip,
    hoverAtIndex,
    renderHogChart,
    setupJsdom,
    setupSyncRaf,
    waitForHogChartTooltip,
} from '../testing'
import { BarChart } from './BarChart'

const THEME: ChartTheme = {
    colors: ['#1f77b4', '#ff7f0e', '#2ca02c'],
    backgroundColor: '#ffffff',
    gridColor: '#eeeeee',
    crosshairColor: '#888888',
}

const SERIES: Series[] = [
    { key: 'a', label: 'A', data: [10, 20, 30] },
    { key: 'b', label: 'B', data: [5, 15, 25] },
]

const LABELS = ['Mon', 'Tue', 'Wed']

type Layout = 'stacked' | 'grouped' | 'percent'
type Orientation = 'vertical' | 'horizontal'

describe('BarChart', () => {
    let teardownJsdom: () => void
    let teardownRaf: () => void

    beforeEach(() => {
        teardownJsdom = setupJsdom()
        teardownRaf = setupSyncRaf()
    })

    afterEach(() => {
        teardownRaf()
        teardownJsdom()
        cleanup()
    })

    describe.each<[Layout, Orientation]>([
        ['stacked', 'vertical'],
        ['grouped', 'vertical'],
        ['percent', 'vertical'],
        ['stacked', 'horizontal'],
        ['grouped', 'horizontal'],
        ['percent', 'horizontal'],
    ])('%s / %s', (barLayout, axisOrientation) => {
        it('renders ticks for the value axis', () => {
            const { chart } = renderHogChart(
                <BarChart series={SERIES} labels={LABELS} theme={THEME} config={{ barLayout, axisOrientation }} />
            )
            const valueTicks = axisOrientation === 'horizontal' ? chart.xTicks() : chart.yTicks()
            expect(valueTicks.length).toBeGreaterThan(0)
        })
    })

    it('forwards `dataAttr` to the chart wrapper for product-test selection', () => {
        const { chart } = renderHogChart(
            <BarChart series={SERIES} labels={LABELS} theme={THEME} dataAttr="bar-chart-instance" />
        )
        expect(chart.element.getAttribute('data-attr')).toBe('bar-chart-instance')
    })

    it('renders empty state without crashing', () => {
        const { chart } = renderHogChart(<BarChart series={[]} labels={[]} theme={THEME} />)
        expect(chart.seriesCount).toBe(0)
    })

    it('renders custom percent formatter when consumer supplies one', () => {
        const formatter = jest.fn((v: number) => `${Math.round(v * 1000) / 10}‰`)
        const { chart } = renderHogChart(
            <BarChart
                series={SERIES}
                labels={LABELS}
                theme={THEME}
                config={{ barLayout: 'percent', yTickFormatter: formatter }}
            />
        )
        expect(formatter).toHaveBeenCalled()
        expect(chart.yTicks().some((t) => t.endsWith('‰'))).toBe(true)
    })

    it('applies a default percent formatter when consumer omits one', () => {
        const { chart } = renderHogChart(
            <BarChart series={SERIES} labels={LABELS} theme={THEME} config={{ barLayout: 'percent' }} />
        )
        expect(chart.yTicks().some((t) => /\d+%/.test(t))).toBe(true)
    })

    it('tolerates NaN data values without throwing', () => {
        const broken: Series[] = [{ key: 'a', label: 'A', data: [Number.NaN, Number.NaN, Number.NaN] }]
        const { chart } = renderHogChart(<BarChart series={broken} labels={LABELS} theme={THEME} />)
        expect(chart.seriesCount).toBe(1)
    })

    describe('series exclusion', () => {
        it.each<[Layout]>([['stacked'], ['grouped'], ['percent']])(
            'skips excluded series in %s layout',
            (barLayout) => {
                const series: Series[] = [
                    { key: 'a', label: 'A', data: [10, 20, 30] },
                    { key: 'b', label: 'B', data: [5, 15, 25], visibility: { excluded: true } },
                    { key: 'c', label: 'C', data: [3, 6, 9] },
                ]
                const { chart } = renderHogChart(
                    <BarChart series={series} labels={LABELS} theme={THEME} config={{ barLayout }} />
                )
                expect(chart.seriesCount).toBe(2)
            }
        )
    })

    describe('axis configuration', () => {
        it('hides x-axis ticks when hideXAxis is true', () => {
            const { chart } = renderHogChart(
                <BarChart series={SERIES} labels={LABELS} theme={THEME} config={{ hideXAxis: true }} />
            )
            expect(chart.xTicks()).toHaveLength(0)
        })

        it('hides y-axis ticks when hideYAxis is true', () => {
            const { chart } = renderHogChart(
                <BarChart series={SERIES} labels={LABELS} theme={THEME} config={{ hideYAxis: true }} />
            )
            expect(chart.yTicks()).toHaveLength(0)
        })

        it('applies xTickFormatter to x-axis ticks', () => {
            const { chart } = renderHogChart(
                <BarChart
                    series={SERIES}
                    labels={LABELS}
                    theme={THEME}
                    config={{ xTickFormatter: (_l, i) => `tick-${i}` }}
                />
            )
            expect(chart.xTicks()).toEqual(['tick-0', 'tick-1', 'tick-2'])
        })

        it('renders without crashing in yScaleType log with positive data', () => {
            const series: Series[] = [{ key: 'a', label: 'A', data: [1, 10, 100] }]
            const { chart } = renderHogChart(
                <BarChart
                    series={series}
                    labels={LABELS}
                    theme={THEME}
                    config={{ yScaleType: 'log', barLayout: 'grouped' }}
                />
            )
            const ticks = chart.yTicks()
            expect(ticks.length).toBeGreaterThan(0)
            for (const t of ticks) {
                expect(Number.isFinite(parseFloat(t.replace(/[^\d.\-eE]/g, '')))).toBe(true)
            }
        })
    })

    describe('hover & tooltip', () => {
        it('mounts a tooltip on hover', async () => {
            const { chart } = renderHogChart(<BarChart series={SERIES} labels={LABELS} theme={THEME} />)
            hoverAtIndex(chart.element, 1, LABELS.length)
            const tooltip = await waitForHogChartTooltip()
            expect(tooltip.textContent).toContain('Tue')
        })

        it('invokes onPointClick with the clicked column', async () => {
            const onPointClick = jest.fn()
            const { chart } = renderHogChart(
                <BarChart series={SERIES} labels={LABELS} theme={THEME} onPointClick={onPointClick} />
            )
            await clickAtIndex(chart.element, 1, LABELS.length)
            expect(onPointClick).toHaveBeenCalledWith(expect.objectContaining({ dataIndex: 1, label: 'Tue' }))
        })

        it('passes hovered seriesData to a custom tooltip render prop', async () => {
            const tooltip = (ctx: TooltipContext): React.ReactNode => (
                <div data-attr="custom-tooltip">{ctx.seriesData.length}</div>
            )
            const { chart } = renderHogChart(
                <BarChart series={SERIES} labels={LABELS} theme={THEME} tooltip={tooltip} />
            )
            hoverAtIndex(chart.element, 1, LABELS.length)
            const node = await waitForHogChartTooltip()
            expect(node.querySelector('[data-attr="custom-tooltip"]')?.textContent).toBe(String(SERIES.length))
        })

        it('pins the tooltip on click when tooltip.pinnable is true', async () => {
            const { chart } = renderHogChart(
                <BarChart series={SERIES} labels={LABELS} theme={THEME} config={{ tooltip: { pinnable: true } }} />
            )
            hoverAtIndex(chart.element, 1, LABELS.length)
            await waitForHogChartTooltip()
            await clickAtIndex(chart.element, 1, LABELS.length)
            expect(getHogChartTooltip()?.classList.contains('hog-charts-tooltip--pinned')).toBe(true)
        })

        it('omits a series from tooltip when visibility.fromTooltip is true', async () => {
            const series: Series[] = [
                { key: 'a', label: 'A', data: [10, 20, 30] },
                { key: 'b', label: 'B', data: [5, 15, 25], visibility: { fromTooltip: true } },
            ]
            const { chart } = renderHogChart(<BarChart series={series} labels={LABELS} theme={THEME} />)
            hoverAtIndex(chart.element, 1, LABELS.length)
            const tooltip = await waitForHogChartTooltip()
            expect(tooltip.textContent).toContain('A')
            expect(tooltip.textContent).not.toContain('B')
        })
    })

    describe('children & error boundary', () => {
        it('renders custom overlay children', () => {
            const { chart } = renderHogChart(
                <BarChart series={SERIES} labels={LABELS} theme={THEME}>
                    <div data-attr="custom-child" />
                </BarChart>
            )
            expect(chart.element.querySelector('[data-attr="custom-child"]')).not.toBeNull()
        })

        it('renders a ReferenceLine child via the accessor', () => {
            const { chart } = renderHogChart(
                <BarChart series={SERIES} labels={LABELS} theme={THEME}>
                    <ReferenceLine value={15} label="Target" />
                </BarChart>
            )
            const lines = chart.referenceLines()
            expect(lines).toHaveLength(1)
            expect(lines[0].label).toBe('Target')
            expect(lines[0].orientation).toBe('horizontal')
        })

        it('reports render errors through onError', async () => {
            const onError = jest.fn()
            const tooltip = (): React.ReactNode => {
                throw new Error('boom')
            }
            const consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {})
            try {
                const { chart } = renderHogChart(
                    <BarChart series={SERIES} labels={LABELS} theme={THEME} tooltip={tooltip} onError={onError} />
                )
                hoverAtIndex(chart.element, 1, LABELS.length)
                await waitFor(() => expect(onError).toHaveBeenCalled())
            } finally {
                consoleErrorSpy.mockRestore()
            }
        })
    })
})
