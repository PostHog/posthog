import { fireEvent, waitFor } from '@testing-library/react'

import type { BarChartConfig, ChartTheme, PointClickData, Series } from '../../core/types'
import { ReferenceLine } from '../../overlays/ReferenceLine'
import { getHogChart, getHogChartTooltip, renderHogChart } from '../../testing'
import { dimensions } from '../../testing/jsdom'
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
        const broken: Series[] = [
            {
                key: 'a',
                label: 'A',
                data: [Number.NaN, Number.NaN, Number.NaN],
            },
        ]
        const { chart } = renderHogChart(<BarChart series={broken} labels={LABELS} theme={THEME} />)
        expect(chart.seriesCount).toBe(1)
    })

    describe('series exclusion', () => {
        it.each<[Layout]>([['stacked'], ['grouped'], ['percent']])(
            'skips excluded series in %s layout',
            (barLayout) => {
                const series: Series[] = [
                    { key: 'a', label: 'A', data: [10, 20, 30] },
                    {
                        key: 'b',
                        label: 'B',
                        data: [5, 15, 25],
                        visibility: { excluded: true },
                    },
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

        it('renders custom axis titles in horizontal orientation', () => {
            const { chart } = renderHogChart(
                <BarChart
                    series={SERIES}
                    labels={LABELS}
                    theme={THEME}
                    config={{
                        axisOrientation: 'horizontal',
                        xAxisLabel: 'Total events',
                        yAxisLabel: 'Series',
                    }}
                />
            )
            expect(chart.xAxisLabel()).toBe('Total events')
            expect(chart.yAxisLabel()).toBe('Series')
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
            // Stacked/percent order is cursor-resolved, so assert membership not declaration order.
            expect(new Set(tooltip.seriesData.map((s) => s.series.key))).toEqual(new Set(expectedKeys))
        })

        it('stacked tooltip shows each series own value, not the cumulative stack total', async () => {
            // At index 1: a=20 (bottom) and b=15 stacked on top. b's stacked top is 35, but the
            // tooltip must report b's own 15 — the segment, not the running total.
            const { chart } = renderHogChart(
                <BarChart series={SERIES} labels={LABELS} theme={THEME} config={{ barLayout: 'stacked' }} />
            )
            chart.hoverAtIndex(1)
            const tooltip = await chart.waitForTooltip()
            expect(tooltip.series.a.value).toBe(20)
            expect(tooltip.series.b.value).toBe(15)
        })

        it('stacked tooltip keeps series in declaration order regardless of cursor height', async () => {
            // At index 1: a=20 (bottom of stack), b=15 (on top). The tooltip lists the whole stack in
            // declaration order — visual top-to-bottom ordering is handled downstream by DefaultTooltip's
            // yPixel sort, so seriesData stays declaration-ordered no matter which segment the cursor is over.
            const { chart } = renderHogChart(
                <BarChart series={SERIES} labels={LABELS} theme={THEME} config={{ barLayout: 'stacked' }} />
            )
            chart.hoverAtIndex(1)
            const tipMid = await chart.waitForTooltip()
            expect(tipMid.seriesData.map((s) => s.series.key)).toEqual(['a', 'b'])
            const step = dimensions.plotWidth / LABELS.length
            // Move the cursor down into a's segment — the data order must not change (no bubbling).
            const NEAR_BOTTOM_OFFSET_PX = 8
            fireEvent.mouseMove(chart.element, {
                clientX: dimensions.plotLeft + step * 1.5,
                clientY: dimensions.plotTop + dimensions.plotHeight - NEAR_BOTTOM_OFFSET_PX,
            })
            const tipLow = await chart.waitForTooltip()
            expect(tipLow.seriesData.map((s) => s.series.key)).toEqual(['a', 'b'])
        })

        // Mirrors the horizontal funnel bar: breakdown segments plus a tooltip-hidden filler
        // padding the stack to 100. seriesData keeps declaration order, so consumers need
        // hoveredSeriesKey to know which segment the cursor is in — including the filler,
        // which has no seriesData row of its own.
        it.each<[string, number, string]>([
            ['first segment', 20, 'a'],
            ['middle segment', 55, 'b'],
            ['tooltip-hidden filler segment', 85, 'filler'],
        ])('stacked exposes hoveredSeriesKey for cursor in the %s', async (_name, valueAtCursor, expectedKey) => {
            const series: Series[] = [
                { key: 'a', label: 'A', data: [40] },
                { key: 'b', label: 'B', data: [30] },
                { key: 'filler', label: 'Filler', data: [30], visibility: { tooltip: false } },
            ]
            const { chart } = renderHogChart(
                <BarChart
                    series={series}
                    labels={['step']}
                    theme={THEME}
                    config={{ barLayout: 'stacked', axisOrientation: 'horizontal' }}
                />
            )
            // Stack totals 100, so the nice value scale spans [0, 100] across the plot width.
            fireEvent.mouseMove(chart.element, {
                clientX: dimensions.plotLeft + (valueAtCursor / 100) * dimensions.plotWidth,
                clientY: dimensions.plotTop + dimensions.plotHeight / 2,
            })
            const tooltip = await chart.waitForTooltip()
            expect(tooltip.hoveredSeriesKey).toBe(expectedKey)
            expect(tooltip.seriesData.map((s) => s.series.key)).toEqual(['a', 'b'])
        })

        it('stacked onPointClick routes to the segment whose rect contains the cursor', async () => {
            const onPointClick = jest.fn()
            const { chart } = renderHogChart(
                <BarChart
                    series={SERIES}
                    labels={LABELS}
                    theme={THEME}
                    config={{ barLayout: 'stacked' }}
                    onPointClick={onPointClick}
                />
            )
            const step = dimensions.plotWidth / LABELS.length
            fireEvent.mouseMove(chart.element, {
                clientX: dimensions.plotLeft + step * 1.5,
                clientY: dimensions.plotTop + dimensions.plotHeight / 2,
            })
            fireEvent.click(chart.element)
            const clickB: PointClickData = onPointClick.mock.calls[0][0]
            expect(clickB.series.key).toBe('b')
            expect(clickB.value).toBe(15)
            expect(clickB.seriesIndex).toBe(1)

            onPointClick.mockClear()
            const NEAR_BOTTOM_OFFSET_PX = 8
            fireEvent.mouseMove(chart.element, {
                clientX: dimensions.plotLeft + step * 1.5,
                clientY: dimensions.plotTop + dimensions.plotHeight - NEAR_BOTTOM_OFFSET_PX,
            })
            fireEvent.click(chart.element)
            const clickA: PointClickData = onPointClick.mock.calls[0][0]
            expect(clickA.series.key).toBe('a')
            expect(clickA.value).toBe(20)
            expect(clickA.seriesIndex).toBe(0)
        })

        it('percent tooltip shows each series own fraction, not the cumulative fraction', async () => {
            // At index 1: a=20, b=15 → total 35. b sits on top of a, so b's cumulative top is 1.0,
            // but the tooltip must report b's own 15/35 fraction — the segment, not the running total.
            const { chart } = renderHogChart(
                <BarChart series={SERIES} labels={LABELS} theme={THEME} config={{ barLayout: 'percent' }} />
            )
            chart.hoverAtIndex(1)
            const tooltip = await chart.waitForTooltip()
            expect(tooltip.series.a.value).toBeCloseTo(20 / 35, 5)
            expect(tooltip.series.b.value).toBeCloseTo(15 / 35, 5)
        })

        it('stacked onPointClick reports each series own value, not the cumulative stack total', async () => {
            const onPointClick = jest.fn()
            const { chart } = renderHogChart(
                <BarChart
                    series={SERIES}
                    labels={LABELS}
                    theme={THEME}
                    config={{ barLayout: 'stacked' }}
                    onPointClick={onPointClick}
                />
            )
            await chart.clickAtIndex(1)
            const clickData: PointClickData = onPointClick.mock.calls[0][0]
            expect(
                clickData.crossSeriesData.map((d) => ({
                    key: d.series.key,
                    value: d.value,
                }))
            ).toEqual([
                { key: 'a', value: 20 },
                { key: 'b', value: 15 },
            ])
        })

        it.each<[string, BarChartConfig]>([
            ['grouped', { barLayout: 'grouped' } as BarChartConfig],
            ['stacked', { barLayout: 'stacked' } as BarChartConfig],
        ])('%s layout suppresses tooltip in the gap between band groups', async (_name, config) => {
            const { chart } = renderHogChart(<BarChart series={SERIES} labels={LABELS} theme={THEME} config={config} />)
            // d3.scaleBand with paddingInner=0.2 and paddingOuter=0.1 yields step = plotWidth / 3
            // for 3 labels. Bands occupy [0.1*step, 0.9*step], [1.1*step, 1.9*step], [2.1*step, 2.9*step]
            // — so x = plotLeft + 1.0*step is centred in the between-group gap.
            const d3Step = dimensions.plotWidth / LABELS.length
            fireEvent.mouseMove(chart.element, {
                clientX: dimensions.plotLeft + d3Step,
                clientY: dimensions.plotTop + dimensions.plotHeight / 2,
            })
            await new Promise((resolve) => setTimeout(resolve, 0))
            const tooltipEl = document.querySelector('[data-hog-charts-tooltip]') as HTMLElement | null
            expect(tooltipEl?.textContent ?? '').toBe('')
        })

        it('stacked horizontal suppresses tooltip past the bar value extent', async () => {
            const { chart } = renderHogChart(
                <BarChart
                    series={SERIES}
                    labels={LABELS}
                    theme={THEME}
                    config={{
                        barLayout: 'stacked',
                        axisOrientation: 'horizontal',
                    }}
                />
            )
            // plotHeight/2 lands in the middle row (Tue), which stacks to 35 while the value axis
            // runs to the global max (Wed = 55) — so the left of the plot is filled bar and the
            // right is empty track.
            const yMidRow = dimensions.plotTop + dimensions.plotHeight / 2
            // Over the bar: tooltip shows.
            fireEvent.mouseMove(chart.element, {
                clientX: dimensions.plotLeft + dimensions.plotWidth * 0.2,
                clientY: yMidRow,
            })
            const tooltip = await chart.waitForTooltip()
            expect(tooltip.element.textContent).toContain('Tue')
            // Past the bar's value extent: tooltip must clear.
            fireEvent.mouseMove(chart.element, {
                clientX: dimensions.plotLeft + dimensions.plotWidth * 0.95,
                clientY: yMidRow,
            })
            await waitFor(() => expect(getHogChartTooltip()?.textContent ?? '').toBe(''))
        })

        describe('sparse-stacked horizontal (overlap layout)', () => {
            // Mirrors `buildTrendsBarAggregatedSeries`: each series has one non-zero value at
            // its own dataIndex, every label is the same band. Smallest bar paints on top, so
            // its colour wins at x=0..20, then mid at 20..50, then big at 50..100.
            const SPARSE_LABELS = ['band', 'band', 'band']
            const SPARSE_SERIES: Series[] = [
                // DESC, matching how `trendsDataLogic` sorts ActionsBarValue results.
                { key: 'big', label: 'Big', data: [100, 0, 0] },
                { key: 'mid', label: 'Mid', data: [0, 50, 0] },
                { key: 'small', label: 'Small', data: [0, 0, 20] },
            ]
            const HORIZONTAL_STACKED: BarChartConfig = {
                barLayout: 'stacked',
                axisOrientation: 'horizontal',
            }
            // Value scale `[0, 100]` (already nice).
            const xForValue = (value: number): number => dimensions.plotLeft + (value / 100) * dimensions.plotWidth
            const yMidBand = dimensions.plotTop + dimensions.plotHeight / 2

            it.each<[string, number, string, number]>([
                ['small slice (0 < x < 20)', 10, 'small', 20],
                ['mid slice (20 < x < 50)', 30, 'mid', 50],
                ['big slice (50 < x < 100)', 75, 'big', 100],
            ])(
                'tooltip surfaces the visible segment with its own value for cursor in the %s',
                async (_name, valueAtCursor, key, expectedValue) => {
                    const { chart } = renderHogChart(
                        <BarChart
                            series={SPARSE_SERIES}
                            labels={SPARSE_LABELS}
                            theme={THEME}
                            config={HORIZONTAL_STACKED}
                        />
                    )
                    fireEvent.mouseMove(chart.element, {
                        clientX: xForValue(valueAtCursor),
                        clientY: yMidBand,
                    })
                    const tooltip = await chart.waitForTooltip()
                    // Rows stay in declaration order (visual ordering is handled by DefaultTooltip),
                    // but the segment under the cursor is revalued to its own dataIndex value rather
                    // than the zero of the band-collapsed cell.
                    const visible = tooltip.seriesData.find((s) => s.series.key === key)
                    expect(visible?.value).toBe(expectedValue)
                }
            )

            it.each<[string, number, string, number, number]>([
                ['small slice', 10, 'small', 20, 2],
                ['mid slice', 30, 'mid', 50, 1],
                ['big slice', 75, 'big', 100, 0],
            ])(
                'onPointClick routes to the visible segment for cursor in the %s',
                async (_name, valueAtCursor, key, expectedValue, expectedSeriesIndex) => {
                    const onPointClick = jest.fn()
                    const { chart } = renderHogChart(
                        <BarChart
                            series={SPARSE_SERIES}
                            labels={SPARSE_LABELS}
                            theme={THEME}
                            config={HORIZONTAL_STACKED}
                            onPointClick={onPointClick}
                        />
                    )
                    fireEvent.mouseMove(chart.element, {
                        clientX: xForValue(valueAtCursor),
                        clientY: yMidBand,
                    })
                    fireEvent.click(chart.element)
                    const click: PointClickData = onPointClick.mock.calls[0][0]
                    expect(click.series.key).toBe(key)
                    expect(click.value).toBe(expectedValue)
                    expect(click.seriesIndex).toBe(expectedSeriesIndex)
                }
            )
        })

        it('grouped layout still narrows when the cursor is above every bar (value-axis miss)', async () => {
            const { chart } = renderHogChart(
                <BarChart series={SERIES} labels={LABELS} theme={THEME} config={{ barLayout: 'grouped' }} />
            )
            // Same x as `hoverAtIndex(1)` (which lands inside `b`'s sub-band) but a y above
            // every bar's top. Without the band-axis-only hit-test this would fail per-bar
            // intersection and fall back to highlighting both `a` and `b`.
            const step = dimensions.plotWidth / (LABELS.length - 1)
            fireEvent.mouseMove(chart.element, {
                clientX: dimensions.plotLeft + step * 1,
                clientY: dimensions.plotTop + 1,
            })
            const tooltip = await chart.waitForTooltip()
            expect(tooltip.seriesData.map((s) => s.series.key)).toEqual(['b'])
            expect(tooltip.hoveredSeriesKey).toBe('b')
        })

        // Regression: grouped clicks always resolved to the first series, so a breakdown
        // funnel opened the persons modal for breakdown 0 regardless of the bar clicked.
        // The cursor is in the track *above* every bar (y near the plot top), so only the
        // band-axis (column) hit-test can route it — full-rect containment would miss and
        // fall back to the first series. This mirrors clicking the track over a short bar.
        it.each<[string, number, string, number]>([
            ['left sub-bar (a)', 1.3, 'a', 20],
            ['right sub-bar (b)', 1.65, 'b', 15],
        ])(
            'grouped onPointClick routes to the sub-bar column under the cursor, even above the bar — %s',
            async (_name, stepMultiplier, key, value) => {
                const onPointClick = jest.fn()
                const { chart } = renderHogChart(
                    <BarChart
                        series={SERIES}
                        labels={LABELS}
                        theme={THEME}
                        config={{ barLayout: 'grouped' }}
                        onPointClick={onPointClick}
                    />
                )
                const step = dimensions.plotWidth / LABELS.length
                fireEvent.mouseMove(chart.element, {
                    clientX: dimensions.plotLeft + step * stepMultiplier,
                    clientY: dimensions.plotTop + 2,
                })
                fireEvent.click(chart.element)
                const click: PointClickData = onPointClick.mock.calls[0][0]
                expect(click.dataIndex).toBe(1)
                expect(click.series.key).toBe(key)
                expect(click.value).toBe(value)
                // Cursor is in the track above the bar's fill — funnel drop-off relies on this.
                expect(click.inTrackArea).toBe(true)
            }
        )

        // Complement of the track test above: a click inside the bar's filled extent must report
        // `inTrackArea: false` so funnel "converted" clicks route correctly.
        it.each<[string, number, string]>([
            ['left sub-bar (a)', 1.3, 'a'],
            ['right sub-bar (b)', 1.65, 'b'],
        ])(
            'grouped onPointClick reports inTrackArea false when the cursor is within the bar fill — %s',
            async (_name, stepMultiplier, key) => {
                const onPointClick = jest.fn()
                const { chart } = renderHogChart(
                    <BarChart
                        series={SERIES}
                        labels={LABELS}
                        theme={THEME}
                        config={{ barLayout: 'grouped' }}
                        onPointClick={onPointClick}
                    />
                )
                const step = dimensions.plotWidth / LABELS.length
                // Same column as the sub-bar at index 1, but just above the baseline so the
                // cursor sits inside the fill rather than in the track above it.
                fireEvent.mouseMove(chart.element, {
                    clientX: dimensions.plotLeft + step * stepMultiplier,
                    clientY: dimensions.plotTop + dimensions.plotHeight - 2,
                })
                fireEvent.click(chart.element)
                const click: PointClickData = onPointClick.mock.calls[0][0]
                expect(click.dataIndex).toBe(1)
                expect(click.series.key).toBe(key)
                expect(click.inTrackArea).toBe(false)
            }
        )

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
                {
                    key: 'b',
                    label: 'B',
                    data: [5, 15, 25],
                    visibility: { tooltip: false },
                },
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

    describe('interactive legend', () => {
        it('renders no legend by default', () => {
            const { container } = renderHogChart(<BarChart series={SERIES} labels={LABELS} theme={THEME} />)
            expect(container.querySelector('[data-attr="hog-chart-bar-legend"]')).toBeNull()
        })

        it('toggles a series off and on when its legend row is clicked', () => {
            const { container, chart } = renderHogChart(
                <BarChart series={SERIES} labels={LABELS} theme={THEME} config={{ legend: { show: true } }} />
            )
            expect(chart.seriesCount).toBe(2)
            const buttons = (): HTMLButtonElement[] =>
                Array.from(container.querySelectorAll('[data-attr="hog-chart-bar-legend"] button'))

            fireEvent.click(buttons()[1])
            expect(getHogChart(container).seriesCount).toBe(1)
            expect(buttons()[1].className).toContain('opacity-40')

            fireEvent.click(buttons()[1])
            expect(getHogChart(container).seriesCount).toBe(2)
        })
    })
})
