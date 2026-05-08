import { waitFor } from '@testing-library/react'

import type { BarChartConfig, ChartTheme, Series } from '../../core/types'
import { ReferenceLine } from '../../overlays/ReferenceLine'
import { renderHogChart } from '../../testing'
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

    it.each<[string, Series[], string[]]>([
        ['single sparse bar', [{ key: 'all', label: 'All events', data: [103000] }], ['All events']],
        [
            'single result with 90-day labels (mismatched)',
            [{ key: 'all', label: 'All events', data: [103000] }],
            Array.from({ length: 90 }, (_, i) => `d${i}`),
        ],
        [
            'two sparse-stacked results',
            [
                { key: 'a', label: 'A', data: [103000, 0] },
                { key: 'b', label: 'B', data: [0, 50000] },
            ],
            ['A', 'B'],
        ],
    ])('horizontal: %s anchors value axis at 0', (_name, series, labels) => {
        const { chart } = renderHogChart(
            <BarChart
                series={series}
                labels={labels}
                theme={THEME}
                config={{ barLayout: 'stacked', axisOrientation: 'horizontal' }}
            />
        )
        const ticks = chart.xTicks().map((t) => Number(t.replace(/,/g, '')))
        // All cases must start at 0 — the value axis should be anchored.
        expect(ticks[0]).toBe(0)
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
            chart.hoverAtIndex(1)
            const tooltip = await chart.waitForTooltip()
            expect(tooltip.element.textContent).toContain('Tue')
        })

        it('invokes onPointClick with the clicked column', async () => {
            const onPointClick = jest.fn()
            const { chart } = renderHogChart(
                <BarChart series={SERIES} labels={LABELS} theme={THEME} onPointClick={onPointClick} />
            )
            await chart.clickAtIndex(1)
            expect(onPointClick).toHaveBeenCalledWith(expect.objectContaining({ dataIndex: 1, label: 'Tue' }))
        })

        it.each([
            {
                name: 'stacked layout carries every visible series in the tooltip',
                config: undefined as BarChartConfig | undefined,
                expectedKeys: ['a', 'b'],
            },
            {
                name: 'grouped layout narrows to the bar under the cursor',
                config: { barLayout: 'grouped' } as BarChartConfig,
                // hoverAtIndex puts the cursor at band-center / mid-plot, which lands in `b`'s sub-band.
                expectedKeys: ['b'],
            },
        ])('$name', async ({ config, expectedKeys }) => {
            const { chart } = renderHogChart(<BarChart series={SERIES} labels={LABELS} theme={THEME} config={config} />)
            chart.hoverAtIndex(1)
            const tooltip = await chart.waitForTooltip()
            expect(tooltip.seriesData.map((s) => s.series.key)).toEqual(expectedKeys)
        })

        it('pins the tooltip on click when tooltip.pinnable is true', async () => {
            const { chart } = renderHogChart(
                <BarChart series={SERIES} labels={LABELS} theme={THEME} config={{ tooltip: { pinnable: true } }} />
            )
            await chart.clickAtIndex(1)
            const tooltip = await chart.waitForTooltip()
            expect(tooltip.isPinned).toBe(true)
        })

        it('omits a series from tooltip when visibility.tooltip is false', async () => {
            const series: Series[] = [
                { key: 'a', label: 'A', data: [10, 20, 30] },
                { key: 'b', label: 'B', data: [5, 15, 25], visibility: { tooltip: false } },
            ]
            const { chart } = renderHogChart(<BarChart series={series} labels={LABELS} theme={THEME} />)
            chart.hoverAtIndex(1)
            const tooltip = await chart.waitForTooltip()
            expect(tooltip.element.textContent).toContain('A')
            expect(tooltip.element.textContent).not.toContain('B')
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
                chart.hoverAtIndex(1)
                await waitFor(() => expect(onError).toHaveBeenCalled())
            } finally {
                consoleErrorSpy.mockRestore()
            }
        })
    })
})
