import '@testing-library/jest-dom'

import { cleanup, configure, fireEvent, screen, waitFor } from '@testing-library/react'

import { dragSelection, setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

import {
    ChartSettings,
    ChartSettingsFormatting,
    DataVisualizationNode,
    NodeKind,
} from '~/queries/schema/schema-general'
import {
    type DataVizFixture,
    buildDataVisualizationQuery,
    getHogChart,
    HOVER,
    MONTHS,
    renderDataVisualization,
    renderWithInsights,
    sqlChart,
} from '~/test/insight-testing'
import { ChartDisplayType } from '~/types'

import { AxisSeries } from '../../dataVisualizationLogic'
import { LineGraphProps } from './LineGraph'
import { SqlLineGraph } from './SqlLineGraph'

// Some blocks below mount the full DataVisualization tree (~7 logics). Neither timeout is set
// globally (jest.setup leaves asyncUtilTimeout at 1s, jest.config has no testTimeout → 5s): the
// heavy mount needs findBy* headroom beyond 1s on CI, and sqlChart.hoverTooltip's internal
// waits (findBy* + tooltip poll) can sum past the 5s default.
configure({ asyncUtilTimeout: 5000 })
jest.setTimeout(15000)

let cleanupJsdom: () => void
let cleanupRaf: () => void

beforeEach(() => {
    cleanupJsdom = setupJsdom()
    cleanupRaf = setupSyncRaf()
})

afterEach(() => {
    cleanupRaf()
    cleanupJsdom()
    cleanup()
})

// Direct-render helpers: mount the SqlLineGraph leaf with hand-built axis series. Used for the
// axis-formatting / dual-axis / start-at-zero cases, which only depend on the y-axis config.
type YSettings = AxisSeries<number | null>['settings']

const stringColumn = (name: string): AxisSeries<string>['column'] => ({
    name,
    type: { name: 'STRING', isNumerical: false },
    label: name,
    dataIndex: 0,
})

const numericColumn = (name: string): AxisSeries<number | null>['column'] => ({
    name,
    type: { name: 'INTEGER', isNumerical: true },
    label: name,
    dataIndex: 1,
})

const xData = (labels: string[]): AxisSeries<string> => ({ column: stringColumn('label'), data: labels })

const ySeries = (name: string, data: (number | null)[], settings: YSettings = {}): AxisSeries<number | null> => ({
    column: numericColumn(name),
    data,
    settings,
})

const props = (overrides: Partial<LineGraphProps>): LineGraphProps => ({
    xData: xData(['Mon', 'Tue', 'Wed']),
    yData: [],
    visualizationType: ChartDisplayType.ActionsLineGraph,
    chartSettings: {},
    ...overrides,
})

const renderChart = async (overrides: Partial<LineGraphProps>): Promise<void> => {
    renderWithInsights({ component: <SqlLineGraph {...props(overrides)} /> })
    await screen.findByLabelText(/chart with/i)
}

const lowestTick = (ticks: string[]): number => Math.min(...ticks.map((t) => parseFloat(t.replace(/[^0-9.eE+-]/g, ''))))

// Full-mount helpers: drive a real SQL insight (DataVisualizationNode) through the
// DataVisualization tree. Used for tooltip / legend / overlay behavior that depends on the live
// render path, with the query result injected via cachedResults (no network).
function lineFixture(columns: { name: string; type?: string; valueAt: (i: number) => unknown }[]): DataVizFixture {
    return {
        columns: ['month', ...columns.map((c) => c.name)],
        types: [['month', 'Date'], ...columns.map((c): [string, string] => [c.name, c.type ?? 'UInt64'])],
        results: MONTHS.map((m, i) => [m, ...columns.map((c) => c.valueAt(i))]),
    }
}

const twoSeries = (): DataVizFixture =>
    lineFixture([
        { name: 'a', valueAt: (i) => (i + 1) * 100 },
        { name: 'b', valueAt: (i) => (i + 1) * 10 },
    ])

const renderLine = (
    chartSettings: ChartSettings,
    fixture: DataVizFixture,
    extra?: Partial<DataVisualizationNode>
): ReturnType<typeof renderDataVisualization> =>
    renderDataVisualization({
        query: buildDataVisualizationQuery({
            display: ChartDisplayType.ActionsLineGraph,
            chartSettings: { xAxis: { column: 'month' }, ...chartSettings },
            ...extra,
        }),
        response: fixture,
    })

describe('SqlLineGraph', () => {
    describe('y-axis tick formatting', () => {
        const waitForYTicks = async (): Promise<string[]> => {
            await waitFor(() => expect(getHogChart().yTicks().length).toBeGreaterThan(0))
            return getHogChart().yTicks()
        }

        it('applies the column prefix/suffix to the left-axis ticks', async () => {
            await renderChart({
                yData: [ySeries('revenue', [1200, 1400, 1300], { formatting: { prefix: '$' } })],
            })

            const ticks = await waitForYTicks()
            expect(ticks.every((tick) => tick.startsWith('$'))).toBe(true)
        })

        it('keeps quill auto-formatted ticks when the column carries no formatting', async () => {
            await renderChart({ yData: [ySeries('count', [1200, 1400, 1300])] })

            const ticks = await waitForYTicks()
            expect(ticks.some((tick) => /[$%]/.test(tick))).toBe(false)
        })

        it('formats each gutter from its own column on a dual-axis chart', async () => {
            await renderChart({
                yData: [
                    ySeries('revenue', [1200, 1400, 1300], { formatting: { prefix: '$' } }),
                    ySeries('conversion', [12, 18, 15], {
                        formatting: { suffix: '%' },
                        display: { yAxisPosition: 'right' },
                    }),
                ],
            })

            await waitFor(() => expect(getHogChart().hasRightAxis).toBe(true))
            const chart = getHogChart()
            const rightTicks = chart.yRightTicks()
            expect(chart.yTicks().every((tick) => tick.startsWith('$'))).toBe(true)
            expect(rightTicks.length).toBeGreaterThan(0)
            expect(rightTicks.every((tick) => tick.endsWith('%'))).toBe(true)
        })

        it('hides only the right gutter when the right axis turns tick labels off', async () => {
            await renderChart({
                chartSettings: { rightYAxisSettings: { showTicks: false } },
                yData: [
                    ySeries('revenue', [1200, 1400, 1300]),
                    ySeries('conversion', [12, 18, 15], { display: { yAxisPosition: 'right' } }),
                ],
            })

            await waitFor(() => expect(getHogChart().yTicks().length).toBeGreaterThan(0))
            expect(getHogChart().yRightTicks()).toHaveLength(0)
        })

        it('floats only the right axis when its begin-at-zero is off', async () => {
            await renderChart({
                chartSettings: { rightYAxisSettings: { startAtZero: false } },
                yData: [
                    ySeries('revenue', [1200, 1400, 1300]),
                    ySeries('conversion', [800, 900, 850], { display: { yAxisPosition: 'right' } }),
                ],
            })

            await waitFor(() => expect(getHogChart().hasRightAxis).toBe(true))
            expect(lowestTick(getHogChart().yRightTicks())).toBeGreaterThan(0)
            expect(lowestTick(getHogChart().yTicks())).toBe(0)
        })
    })

    describe('start at zero', () => {
        const waitForYTicks = async (): Promise<string[]> => {
            await waitFor(() => expect(getHogChart().yTicks().length).toBeGreaterThan(0))
            return getHogChart().yTicks()
        }

        it('clamps the left-axis baseline to 0 by default', async () => {
            await renderChart({ yData: [ySeries('latency', [820, 860, 840])] })

            expect(lowestTick(await waitForYTicks())).toBe(0)
        })

        it('floats the left axis to the data range when startAtZero is false', async () => {
            await renderChart({
                yData: [ySeries('latency', [820, 860, 840])],
                chartSettings: { leftYAxisSettings: { startAtZero: false } },
            })

            expect(lowestTick(await waitForYTicks())).toBeGreaterThan(0)
        })
    })

    describe('tooltip', () => {
        it('shows the series value, swatch, and hovered x-label for a single series', async () => {
            renderLine(
                { yAxis: [{ column: 'pageviews' }] },
                lineFixture([{ name: 'pageviews', valueAt: (i) => (i + 1) * 100 }])
            )

            const tooltip = await sqlChart.hoverTooltip(HOVER, MONTHS.length)

            expect(tooltip.value('pageviews')).toBe('300')
            expect(tooltip.label()).toBe('Dec 1, 2025')
            expect(tooltip.swatchColors()).toEqual([expect.stringMatching(/^rgb/)])
        })

        it('shows one row per series with its own value', async () => {
            renderLine({ yAxis: [{ column: 'a' }, { column: 'b' }] }, twoSeries())

            await screen.findByLabelText(/chart with 2 data series/i)
            const tooltip = await sqlChart.hoverTooltip(HOVER, MONTHS.length)

            expect(tooltip.rows()).toEqual(['a', 'b'])
            expect(tooltip.value('a')).toBe('300')
            expect(tooltip.value('b')).toBe('30')
        })

        it.each<{ name: string; formatting: ChartSettingsFormatting; value: number; expected: string }>([
            { name: 'thousands separators', formatting: { style: 'number' }, value: 12345, expected: '12,345' },
            { name: 'compact short', formatting: { style: 'short' }, value: 12345, expected: '12.3 K' },
            { name: 'percent (scaled x100)', formatting: { style: 'percent' }, value: 12.5, expected: '1,250%' },
            { name: 'fixed decimals', formatting: { decimalPlaces: 2 }, value: 3.14159, expected: '3.14' },
            { name: 'prefix', formatting: { prefix: '$' }, value: 3000, expected: '$3000' },
            { name: 'suffix', formatting: { suffix: ' ms' }, value: 3000, expected: '3000 ms' },
        ])('formats the tooltip value with $name', async ({ formatting, value, expected }) => {
            renderLine(
                { yAxis: [{ column: 'a', settings: { formatting } }] },
                lineFixture([{ name: 'a', type: 'Float64', valueAt: (i) => (i === HOVER ? value : value / 2) }])
            )

            const tooltip = await sqlChart.hoverTooltip(HOVER, MONTHS.length)

            // compactNumber separates magnitude with a non-breaking space; normalize for comparison.
            expect(tooltip.value('a')?.replace(/\u00a0/g, ' ')).toBe(expected)
        })

        it.each([
            { name: 'shows a total row for two or more series', showTotalRow: undefined, expectedTotal: '330' },
            { name: 'hides the total row when showTotalRow is false', showTotalRow: false, expectedTotal: undefined },
        ])('$name', async ({ showTotalRow, expectedTotal }) => {
            renderLine({ yAxis: [{ column: 'a' }, { column: 'b' }], showTotalRow }, twoSeries())

            await screen.findByLabelText(/chart with 2 data series/i)
            const tooltip = await sqlChart.hoverTooltip(HOVER, MONTHS.length)

            expect(tooltip.total()).toBe(expectedTotal)
        })
    })

    describe('per-series color', () => {
        it('pins explicit display colors onto each tooltip swatch', async () => {
            renderLine(
                {
                    yAxis: [
                        { column: 'a', settings: { display: { color: '#ff0000' } } },
                        { column: 'b', settings: { display: { color: '#00ff00' } } },
                    ],
                },
                twoSeries()
            )

            await screen.findByLabelText(/chart with 2 data series/i)
            const tooltip = await sqlChart.hoverTooltip(HOVER, MONTHS.length)

            expect(tooltip.swatchColors()).toEqual(['rgb(255, 0, 0)', 'rgb(0, 255, 0)'])
        })
    })

    describe('legend', () => {
        const getLegend = (container: HTMLElement): HTMLElement =>
            container.querySelector<HTMLElement>('[data-attr="hog-chart-timeseries-line-legend"]')!

        it('renders an in-chart legend listing every series when showLegend is set', async () => {
            const { container } = renderLine(
                { yAxis: [{ column: 'a' }, { column: 'b' }], showLegend: true },
                twoSeries()
            )

            await screen.findByLabelText(/chart with 2 data series/i)
            const labels = [...getLegend(container).querySelectorAll('button')].map((b) => b.textContent)
            expect(labels).toEqual(['a', 'b'])
        })

        it('renders no legend by default', async () => {
            const { container } = renderLine({ yAxis: [{ column: 'a' }, { column: 'b' }] }, twoSeries())

            await screen.findByLabelText(/chart with 2 data series/i)
            expect(container.querySelector('[data-attr="hog-chart-timeseries-line-legend"]')).not.toBeInTheDocument()
        })

        it('hides a series from the chart and tooltip when its legend item is toggled off', async () => {
            const { container } = renderLine(
                { yAxis: [{ column: 'a' }, { column: 'b' }], showLegend: true },
                twoSeries()
            )

            await screen.findByLabelText(/chart with 2 data series/i)
            const bButton = [...getLegend(container).querySelectorAll('button')].find((b) =>
                b.textContent?.includes('b')
            )!
            fireEvent.click(bButton)

            await waitFor(() => expect(getHogChart().seriesCount).toBe(1))
            const tooltip = await sqlChart.hoverTooltip(HOVER, MONTHS.length)
            expect(tooltip.rows()).toEqual(['a'])
        })
    })

    describe('axis titles', () => {
        it.each([
            {
                name: 'renders custom axis titles from chart settings',
                settings: { xAxisLabel: 'Signup month', leftYAxisSettings: { label: 'Unique users' } },
                expectedX: 'Signup month',
                expectedY: 'Unique users',
            },
            { name: 'renders no axis titles when none are configured', settings: {}, expectedX: null, expectedY: null },
        ])('$name', async ({ settings, expectedX, expectedY }) => {
            renderLine(
                { yAxis: [{ column: 'pageviews' }], ...settings },
                lineFixture([{ name: 'pageviews', valueAt: (i) => (i + 1) * 100 }])
            )

            await screen.findByLabelText(/chart with/i)
            expect(getHogChart().xAxisLabel()).toBe(expectedX)
            expect(getHogChart().yAxisLabel()).toBe(expectedY)
        })
    })

    describe('x-axis ticks', () => {
        it('formats a date x-axis into readable tick labels', async () => {
            renderLine(
                { yAxis: [{ column: 'pageviews' }] },
                lineFixture([{ name: 'pageviews', valueAt: (i) => (i + 1) * 100 }])
            )

            await screen.findByLabelText(/chart with/i)
            await waitFor(() => expect(getHogChart().xTicks().length).toBeGreaterThan(0))
            // Date-axis tick formatter renders month names (year shown at the Jan boundary).
            expect(getHogChart().xTicks()).toEqual(expect.arrayContaining(['October', 'November', 'December']))
        })

        it('hides x-axis ticks when showXAxisTicks is false', async () => {
            renderLine(
                { yAxis: [{ column: 'pageviews' }], showXAxisTicks: false },
                lineFixture([{ name: 'pageviews', valueAt: (i) => (i + 1) * 100 }])
            )

            await screen.findByLabelText(/chart with/i)
            expect(getHogChart().xTicks()).toHaveLength(0)
        })
    })

    describe('y-axis scale', () => {
        it('renders logarithmic ticks when the left axis scale is logarithmic', async () => {
            renderLine(
                { yAxis: [{ column: 'a' }], leftYAxisSettings: { scale: 'logarithmic' } },
                lineFixture([{ name: 'a', valueAt: (i) => (i + 1) * 100 }])
            )

            await screen.findByLabelText(/chart with/i)
            await waitFor(() => expect(getHogChart().yTicks().length).toBeGreaterThan(0))
            // A log axis lays out ticks per power of ten (10, 20, … 100, 200, …) rather than evenly.
            expect(getHogChart().yTicks()).toEqual(expect.arrayContaining(['10', '100']))
        })
    })

    describe('trend lines', () => {
        it('adds a trend-line series without adding a tooltip row', async () => {
            renderLine(
                { yAxis: [{ column: 'a', settings: { display: { trendLine: true } } }] },
                lineFixture([{ name: 'a', valueAt: (i) => (i + 1) * 100 }])
            )

            // One data series + one trend line = 2 rendered series.
            await waitFor(() => expect(getHogChart().seriesCount).toBe(2))

            const tooltip = await sqlChart.hoverTooltip(HOVER, MONTHS.length)
            expect(tooltip.rows()).toEqual(['a'])
        })
    })

    describe('goal lines', () => {
        it.each([
            {
                name: 'renders a goal line with its label',
                goalLines: [{ label: 'Target', value: 250, displayIfCrossed: true }],
                expectedLabels: ['Target'],
            },
            {
                name: 'renders multiple goal lines in order',
                goalLines: [
                    { label: 'Floor', value: 50, displayIfCrossed: true },
                    { label: 'Ceiling', value: 550, displayIfCrossed: true },
                ],
                expectedLabels: ['Floor', 'Ceiling'],
            },
        ])('$name', async ({ goalLines, expectedLabels }) => {
            renderLine(
                { yAxis: [{ column: 'a' }], goalLines },
                lineFixture([{ name: 'a', valueAt: (i) => (i + 1) * 100 }])
            )

            await screen.findByLabelText(/chart with/i)
            const lines = getHogChart().referenceLines()
            expect(lines.map((l) => l.label)).toEqual(expectedLabels)
            expect(lines.map((l) => l.orientation)).toEqual(expectedLabels.map(() => 'horizontal'))
        })
    })

    describe('area chart', () => {
        it('renders an area graph with the correct tooltip value', async () => {
            renderDataVisualization({
                query: buildDataVisualizationQuery({
                    display: ChartDisplayType.ActionsAreaGraph,
                    chartSettings: { xAxis: { column: 'month' }, yAxis: [{ column: 'a' }, { column: 'b' }] },
                }),
                response: twoSeries(),
            })

            await screen.findByLabelText(/chart with 2 data series/i)
            const tooltip = await sqlChart.hoverTooltip(HOVER, MONTHS.length)
            expect(tooltip.value('a')).toBe('300')
        })
    })

    describe('null handling', () => {
        const withGap = (): DataVizFixture =>
            lineFixture([{ name: 'a', valueAt: (i) => (i === HOVER ? null : (i + 1) * 100) }])

        it.each([
            {
                name: 'draws a null as a gap — the point is absent from the tooltip',
                showNullsAsZero: undefined,
                expected: undefined,
            },
            { name: 'plots a null as zero when showNullsAsZero is set', showNullsAsZero: true, expected: '0' },
        ])('$name', async ({ showNullsAsZero, expected }) => {
            renderLine({ yAxis: [{ column: 'a' }], showNullsAsZero }, withGap())

            const tooltip = await sqlChart.hoverTooltip(HOVER, MONTHS.length)
            expect(tooltip.value('a')).toBe(expected)
        })
    })

    describe('custom series label', () => {
        const legendText = (): string =>
            document.querySelector('[data-attr="hog-chart-timeseries-line-legend"]')?.textContent ?? ''

        it('shows the custom display label in the legend, not the column name', async () => {
            await renderChart({
                yData: [ySeries('mrr_usd', [1, 2, 3], { display: { label: 'Monthly revenue' } })],
                chartSettings: { showLegend: true },
            })

            await waitFor(() => expect(legendText()).toContain('Monthly revenue'))
            expect(legendText()).not.toContain('mrr_usd')
        })
    })

    describe('drag-to-zoom', () => {
        const zoomableQuery = (sql: string, display = ChartDisplayType.ActionsLineGraph): DataVisualizationNode =>
            buildDataVisualizationQuery({
                source: { kind: NodeKind.HogQLQuery, query: sql },
                display,
                chartSettings: { xAxis: { column: 'month' }, yAxis: [{ column: 'pageviews' }] },
            })
        const fixture = (): DataVizFixture => lineFixture([{ name: 'pageviews', valueAt: (i) => (i + 1) * 100 }])

        async function dragAcrossChart(): Promise<void> {
            const canvas = await screen.findByLabelText(/chart with/i)
            dragSelection(canvas.parentElement!, 1, 3, MONTHS.length)
        }

        it.each([
            ['line', ChartDisplayType.ActionsLineGraph],
            ['bar', ChartDisplayType.ActionsBar],
        ])(
            '%s: writes the dragged x values to filters.dateRange when the SQL consumes {filters}',
            async (_, display) => {
                const setQuery = jest.fn()
                renderDataVisualization({
                    query: zoomableQuery('SELECT month, pageviews FROM events WHERE {filters} GROUP BY month', display),
                    response: fixture(),
                    readOnly: false,
                    setQuery,
                })

                await dragAcrossChart()

                await waitFor(() => {
                    expect(setQuery).toHaveBeenCalledWith(
                        expect.objectContaining({
                            source: expect.objectContaining({
                                filters: expect.objectContaining({
                                    dateRange: { date_from: MONTHS[1], date_to: MONTHS[3] },
                                }),
                            }),
                        })
                    )
                })
            }
        )

        it('routes the drag through context.onDateRangeZoom on read-only views', async () => {
            const onDateRangeZoom = jest.fn()
            renderDataVisualization({
                query: zoomableQuery('SELECT month, pageviews FROM events WHERE {filters} GROUP BY month'),
                response: fixture(),
                readOnly: true,
                context: { onDateRangeZoom },
            })

            await dragAcrossChart()

            await waitFor(() => {
                expect(onDateRangeZoom).toHaveBeenCalledWith(MONTHS[1], MONTHS[3])
            })
        })

        it('ignores drags when the SQL does not reference {filters}', async () => {
            const setQuery = jest.fn()
            renderDataVisualization({
                query: zoomableQuery('SELECT month, pageviews FROM events GROUP BY month'),
                response: fixture(),
                readOnly: false,
                setQuery,
            })

            await dragAcrossChart()

            // filters.dateRange would silently not apply, so the gesture must not write it.
            // (setQuery does fire on mount for unrelated settings syncing — inspect the payloads.)
            const dateRangeWrites = setQuery.mock.calls.filter(
                ([q]) => (q as DataVisualizationNode).source.filters?.dateRange
            )
            expect(dateRangeWrites).toEqual([])
        })
    })

    describe('show values on series', () => {
        const waitForValueLabels = async (): Promise<string[]> => {
            await waitFor(() => expect(getHogChart().valueLabels().length).toBeGreaterThan(0))
            return getHogChart()
                .valueLabels()
                .map((label) => label.text)
        }

        it('draws a label per point formatted with the column settings', async () => {
            await renderChart({
                yData: [ySeries('revenue', [1200, 1400, 1300], { formatting: { prefix: '$' } })],
                chartSettings: { showValuesOnSeries: true },
            })

            const labels = await waitForValueLabels()
            expect(labels).toContain('$1200')
            expect(labels).toContain('$1400')
        })

        it('draws no value labels when showValuesOnSeries is off', async () => {
            await renderChart({ yData: [ySeries('revenue', [1200, 1400, 1300])] })

            expect(getHogChart().valueLabels()).toHaveLength(0)
        })
    })
})
