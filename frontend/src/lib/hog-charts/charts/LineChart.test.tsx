import type { ChartTheme, Series } from '../core/types'
import { ReferenceLine } from '../overlays/ReferenceLine'
import { renderHogChart } from '../testing'
import { LineChart } from './LineChart'

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

describe('LineChart', () => {
    it.each([
        ['default config', SERIES, undefined],
        ['area mode', [{ key: 'a', label: 'A', data: [10, 20, 30], fill: {} }] as Series[], undefined],
        ['percent stack mode', SERIES, { percentStackView: true }],
    ] as const)('renders without throwing in %s', (_, series, config) => {
        const { chart } = renderHogChart(<LineChart series={series} labels={LABELS} theme={THEME} config={config} />)
        expect(chart.seriesCount).toBeGreaterThan(0)
    })

    it('renders empty state without crashing', () => {
        const { chart } = renderHogChart(<LineChart series={[]} labels={[]} theme={THEME} />)
        expect(chart.seriesCount).toBe(0)
    })

    it('skips excluded series', () => {
        const series: Series[] = [
            { key: 'a', label: 'A', data: [10, 20, 30] },
            { key: 'b', label: 'B', data: [5, 15, 25], visibility: { excluded: true } },
            { key: 'c', label: 'C', data: [3, 6, 9] },
        ]
        const { chart } = renderHogChart(<LineChart series={series} labels={LABELS} theme={THEME} />)
        expect(chart.seriesCount).toBe(2)
    })

    it('forwards `dataAttr` to the chart wrapper for product-test selection', () => {
        const { chart } = renderHogChart(
            <LineChart series={SERIES} labels={LABELS} theme={THEME} dataAttr="line-chart-instance" />
        )
        expect(chart.element.getAttribute('data-attr')).toBe('line-chart-instance')
    })

    it('applies a default percent formatter when consumer omits one in percent stack mode', () => {
        const { chart } = renderHogChart(
            <LineChart series={SERIES} labels={LABELS} theme={THEME} config={{ percentStackView: true }} />
        )
        expect(chart.yTicks().some((t) => /\d+%/.test(t))).toBe(true)
    })

    it('uses custom yTickFormatter when supplied in percent stack mode', () => {
        const formatter = jest.fn((v: number) => `${Math.round(v * 1000) / 10}‰`)
        const { chart } = renderHogChart(
            <LineChart
                series={SERIES}
                labels={LABELS}
                theme={THEME}
                config={{ percentStackView: true, yTickFormatter: formatter }}
            />
        )
        expect(formatter).toHaveBeenCalled()
        expect(chart.yTicks().some((t) => t.endsWith('‰'))).toBe(true)
    })

    it('tolerates NaN data values without throwing', () => {
        const broken: Series[] = [{ key: 'a', label: 'A', data: [Number.NaN, Number.NaN, Number.NaN] }]
        const { chart } = renderHogChart(<LineChart series={broken} labels={LABELS} theme={THEME} />)
        expect(chart.seriesCount).toBe(1)
    })

    describe('axis configuration', () => {
        it.each([
            ['hideXAxis', { hideXAxis: true }, 'xTicks'],
            ['hideYAxis', { hideYAxis: true }, 'yTicks'],
        ] as const)('hides ticks when %s is true', (_, config, accessor) => {
            const { chart } = renderHogChart(
                <LineChart series={SERIES} labels={LABELS} theme={THEME} config={config} />
            )
            expect(chart[accessor]()).toHaveLength(0)
        })

        it('applies xTickFormatter to x-axis ticks', () => {
            const { chart } = renderHogChart(
                <LineChart
                    series={SERIES}
                    labels={LABELS}
                    theme={THEME}
                    config={{ xTickFormatter: (_l, i) => `tick-${i}` }}
                />
            )
            expect(chart.xTicks()).toEqual(['tick-0', 'tick-1', 'tick-2'])
        })

        it('renders custom axis titles', () => {
            const { chart } = renderHogChart(
                <LineChart
                    series={SERIES}
                    labels={LABELS}
                    theme={THEME}
                    config={{ xAxisLabel: 'Signup date', yAxisLabel: 'Unique users' }}
                />
            )
            expect(chart.xAxisLabel()).toBe('Signup date')
            expect(chart.yAxisLabel()).toBe('Unique users')
        })

        it('includes custom axis titles in the canvas accessible label', () => {
            const { getByRole } = renderHogChart(
                <LineChart
                    series={SERIES}
                    labels={LABELS}
                    theme={THEME}
                    config={{ xAxisLabel: 'Signup date', yAxisLabel: 'Unique users' }}
                />
            )
            expect(getByRole('img').getAttribute('aria-label')).toBe(
                'Chart with 2 data series. X-axis: Signup date. Y-axis: Unique users'
            )
        })

        it('ignores whitespace-only axis titles', () => {
            const { chart, getByRole } = renderHogChart(
                <LineChart
                    series={SERIES}
                    labels={LABELS}
                    theme={THEME}
                    config={{ xAxisLabel: '   ', yAxisLabel: '   ' }}
                />
            )

            expect(chart.xAxisLabel()).toBeNull()
            expect(chart.yAxisLabel()).toBeNull()
            expect(getByRole('img').getAttribute('aria-label')).toBe('Chart with 2 data series')
        })

        it('truncates long axis titles without losing the full label metadata', () => {
            const xAxisLabel = 'Signup date for a very long customer lifecycle analysis '.repeat(30).trim()
            const yAxisLabel = 'Unique users with a very long aggregation description '.repeat(30).trim()
            const { chart } = renderHogChart(
                <LineChart series={SERIES} labels={LABELS} theme={THEME} config={{ xAxisLabel, yAxisLabel }} />
            )

            const xTitle = chart.xAxisLabelElement()
            const yTitle = chart.yAxisLabelElement()
            expect(xTitle?.textContent).toMatch(/\u2026$/)
            expect(yTitle?.textContent).toMatch(/\u2026$/)
            expect(xTitle?.textContent).not.toBe(xAxisLabel)
            expect(yTitle?.textContent).not.toBe(yAxisLabel)
            expect(xTitle?.getAttribute('data-full-label')).toBe(xAxisLabel)
            expect(yTitle?.getAttribute('data-full-label')).toBe(yAxisLabel)
            expect(yTitle?.getAttribute('transform')).toContain('rotate(-90')
        })

        it('hides an axis title when that axis is hidden', () => {
            const { chart } = renderHogChart(
                <LineChart
                    series={SERIES}
                    labels={LABELS}
                    theme={THEME}
                    config={{ xAxisLabel: 'Signup date', yAxisLabel: 'Unique users', hideXAxis: true }}
                />
            )
            expect(chart.xAxisLabel()).toBeNull()
            expect(chart.yAxisLabel()).toBe('Unique users')
        })

        it('renders a right axis when a series sets yAxisId: right', () => {
            const series: Series[] = [
                { key: 'a', label: 'A', data: [10, 20, 30] },
                { key: 'b', label: 'B', data: [1000, 2000, 3000], yAxisId: 'right' },
            ]
            const { chart } = renderHogChart(<LineChart series={series} labels={LABELS} theme={THEME} />)
            expect(chart.hasRightAxis).toBe(true)
            expect(chart.yRightTicks().length).toBeGreaterThan(0)
        })

        it('renders without crashing in yScaleType log with positive data', () => {
            const series: Series[] = [{ key: 'a', label: 'A', data: [1, 10, 100] }]
            const { chart } = renderHogChart(
                <LineChart series={series} labels={LABELS} theme={THEME} config={{ yScaleType: 'log' }} />
            )
            const ticks = chart.yTicks()
            expect(ticks.length).toBeGreaterThan(0)
            for (const t of ticks) {
                expect(Number.isFinite(parseFloat(t.replace(/[^0-9.\-eE]/g, '')))).toBe(true)
            }
        })
    })

    describe('hover & tooltip', () => {
        it('mounts a tooltip on hover', async () => {
            const { chart } = renderHogChart(<LineChart series={SERIES} labels={LABELS} theme={THEME} />)
            chart.hoverAtIndex(1)
            const tooltip = await chart.waitForTooltip()
            expect(tooltip.element.textContent).toContain('Tue')
        })

        it('invokes onPointClick with the clicked column', async () => {
            const onPointClick = jest.fn()
            const { chart } = renderHogChart(
                <LineChart series={SERIES} labels={LABELS} theme={THEME} onPointClick={onPointClick} />
            )
            await chart.clickAtIndex(1)
            expect(onPointClick).toHaveBeenCalledWith(
                expect.objectContaining({ dataIndex: 1, label: 'Tue', value: 20 })
            )
        })

        it('passes hovered seriesData to the tooltip render prop', async () => {
            const { chart } = renderHogChart(<LineChart series={SERIES} labels={LABELS} theme={THEME} />)
            chart.hoverAtIndex(1)
            const tooltip = await chart.waitForTooltip()
            expect(tooltip.seriesData).toHaveLength(SERIES.length)
        })

        it('pins the tooltip on click when tooltip.pinnable is true', async () => {
            const { chart } = renderHogChart(
                <LineChart series={SERIES} labels={LABELS} theme={THEME} config={{ tooltip: { pinnable: true } }} />
            )
            await chart.clickAtIndex(1)
            const tooltip = await chart.waitForTooltip()
            expect(tooltip.isPinned).toBe(true)
        })

        it('does not crash on hover for overlay series', async () => {
            const series: Series[] = [
                { key: 'a', label: 'A', data: [10, 20, 30] },
                { key: 'b', label: 'B', data: [5, 15, 25], overlay: true },
            ]
            const { chart } = renderHogChart(<LineChart series={series} labels={LABELS} theme={THEME} />)
            chart.hoverAtIndex(1)
            const tooltip = await chart.waitForTooltip()
            expect(tooltip.element.textContent).toContain('Tue')
        })

        it('omits a series from tooltip when visibility.tooltip is false', async () => {
            const series: Series[] = [
                { key: 'a', label: 'A', data: [10, 20, 30] },
                { key: 'b', label: 'B', data: [5, 15, 25], visibility: { tooltip: false } },
            ]
            const { chart } = renderHogChart(<LineChart series={series} labels={LABELS} theme={THEME} />)
            chart.hoverAtIndex(1)
            const tooltip = await chart.waitForTooltip()
            expect(tooltip.element.textContent).toContain('A')
            expect(tooltip.element.textContent).not.toContain('B')
        })
    })

    describe('children & error boundary', () => {
        it('renders custom overlay children', () => {
            const { chart } = renderHogChart(
                <LineChart series={SERIES} labels={LABELS} theme={THEME}>
                    <div data-attr="custom-child" />
                </LineChart>
            )
            expect(chart.element.querySelector('[data-attr="custom-child"]')).not.toBeNull()
        })

        it('renders a ReferenceLine child via the accessor', () => {
            const { chart } = renderHogChart(
                <LineChart series={SERIES} labels={LABELS} theme={THEME}>
                    <ReferenceLine value={15} label="Target" />
                </LineChart>
            )
            const lines = chart.referenceLines()
            expect(lines).toHaveLength(1)
            expect(lines[0].label).toBe('Target')
            expect(lines[0].orientation).toBe('horizontal')
        })

        it('reports render errors through onError', () => {
            const onError = jest.fn()
            const tooltip = (): React.ReactNode => {
                throw new Error('boom')
            }
            // ChartErrorBoundary surfaces the error to onError; React still logs it.
            const consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {})
            try {
                const { chart } = renderHogChart(
                    <LineChart series={SERIES} labels={LABELS} theme={THEME} tooltip={tooltip} onError={onError} />
                )
                chart.hoverAtIndex(1)
                expect(onError).toHaveBeenCalled()
            } finally {
                consoleErrorSpy.mockRestore()
            }
        })
    })
})
