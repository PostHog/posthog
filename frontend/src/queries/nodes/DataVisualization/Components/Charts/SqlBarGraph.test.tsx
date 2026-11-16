import '@testing-library/jest-dom'

import { cleanup, configure, fireEvent, screen, waitFor } from '@testing-library/react'

import { clickAtIndex, setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

import { BIConfig } from '~/queries/schema/schema-business-intelligence'
import { NodeKind, ChartSettings } from '~/queries/schema/schema-general'
import {
    type DataVizFixture,
    buildDataVisualizationQuery,
    getChart,
    HOVER,
    MONTHS,
    renderDataVisualization,
    sqlChart,
} from '~/test/insight-testing'
import { ChartDisplayType } from '~/types'

import { buildBIQuery } from 'products/business_intelligence/frontend/biEditorTypes'

// Neither timeout is set globally (jest.setup leaves asyncUtilTimeout at 1s, jest.config has no
// testTimeout → 5s): this heavy ~7-logic mount needs findBy* headroom beyond 1s on CI, and
// sqlChart.hoverTooltip's internal waits (findBy* + tooltip poll) can sum past the 5s default.
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

function barFixture(columns: { name: string; valueAt: (i: number) => unknown }[]): DataVizFixture {
    return {
        columns: ['month', ...columns.map((c) => c.name)],
        types: [['month', 'Date'], ...columns.map((c): [string, string] => [c.name, 'UInt64'])],
        results: MONTHS.map((m, i) => [m, ...columns.map((c) => c.valueAt(i))]),
    }
}

const twoSeries = (): DataVizFixture =>
    barFixture([
        { name: 'a', valueAt: (i) => (i + 1) * 100 },
        { name: 'b', valueAt: (i) => (i + 1) * 10 },
    ])

const renderBar = (
    display: ChartDisplayType,
    chartSettings: ChartSettings,
    fixture: DataVizFixture
): ReturnType<typeof renderDataVisualization> =>
    renderDataVisualization({
        query: buildDataVisualizationQuery({
            display,
            chartSettings: { xAxis: { column: 'month' }, ...chartSettings },
        }),
        response: fixture,
    })

describe('SqlBarGraph', () => {
    it.each([
        ...[ChartDisplayType.ActionsBar, ChartDisplayType.ActionsStackedBar, ChartDisplayType.ActionsBarValue].map(
            (chartType) => ({ chartType, dateBucket: 'month' as const, dates: MONTHS })
        ),
        {
            chartType: ChartDisplayType.ActionsBar,
            dateBucket: 'year' as const,
            dates: ['2023-01-01', '2024-01-01', '2025-01-01', '2026-01-01', '2027-01-01', '2028-01-01'],
        },
    ])(
        'opens BI drilldown and preserves unaliased $dateBucket formatting in $chartType',
        async ({ chartType, dateBucket, dates }) => {
            const config: BIConfig = {
                source: { table: 'events' },
                rows: [
                    {
                        id: 'month',
                        name: 'month',
                        expression: 'timestamp',
                        type: 'datetime',
                        source: { table: 'events' },
                        dateBucket,
                    },
                ],
                columns: [],
                values: [
                    {
                        field: { id: 'a', name: 'a', expression: 'a', type: 'integer', source: { table: 'events' } },
                        aggregation: 'sum',
                    },
                    {
                        field: { id: 'b', name: 'b', expression: 'b', type: 'integer', source: { table: 'events' } },
                        aggregation: 'sum',
                    },
                ],
                filters: [],
                memberAliases: [
                    {
                        field: {
                            id: 'month',
                            name: 'month',
                            expression: 'timestamp',
                            type: 'datetime',
                            source: { table: 'events' },
                            dateBucket,
                        },
                        aliases: [{ value: dates[0], label: 'Campaign start' }],
                    },
                ],
                chartType,
                limit: 100,
            }
            const dateColumn = `toStartOf${dateBucket === 'year' ? 'Year' : 'Month'}(timestamp)`
            const node = buildBIQuery(config)!.node
            renderDataVisualization({
                query: {
                    ...node,
                    kind: NodeKind.BIVisualizationNode,
                    config,
                    chartSettings: {
                        xAxis: { column: dateColumn },
                        yAxis: [{ column: 'sum_a' }, { column: 'sum_b_2' }],
                    },
                },
                response: {
                    columns: [dateColumn, 'sum_a', 'sum_b_2'],
                    types: [
                        [dateColumn, 'DateTime'],
                        ['sum_a', 'UInt64'],
                        ['sum_b_2', 'UInt64'],
                    ],
                    results: MONTHS.map((month, index) => [month, (index + 1) * 100, (index + 1) * 10]),
                },
            })
            const canvas = await screen.findByLabelText(/chart with 2 data series/i)
            expect([...getChart().xTicks(), ...getChart().yTicks()].some((tick) => /^202[56]-/.test(tick))).toBe(false)
            if (dateBucket === 'year') {
                expect(getChart().xTicks()).toContain('2025')
            } else if (chartType !== ChartDisplayType.ActionsBarValue) {
                expect((await sqlChart.hoverTooltip(HOVER)).label()).toBe('Dec 1, 00:00')
            }
            await clickAtIndex(canvas.parentElement!, HOVER, dates.length)
            expect(await screen.findByText('Explore this result')).toBeVisible()
            expect(screen.getByText('View underlying rows')).toBeVisible()
            expect(screen.getByText(/month: 202[56]-/)).toBeVisible()
        }
    )

    describe('bar layouts', () => {
        it('keeps horizontal BI category positions separate when their display aliases match', async () => {
            const region = {
                id: 'region',
                name: 'Region',
                expression: 'region',
                type: 'string' as const,
                source: { table: 'example_orders' },
            }
            const config: BIConfig = {
                source: region.source,
                rows: [region],
                columns: [],
                filters: [],
                limit: 100,
                chartType: ChartDisplayType.ActionsBarValue,
                values: [
                    {
                        field: { ...region, id: 'amount', name: 'Amount', expression: 'amount', type: 'float' },
                        aggregation: 'sum',
                    },
                ],
                memberAliases: [
                    {
                        field: region,
                        aliases: [
                            { value: 'east', label: 'Same label' },
                            { value: 'west', label: 'Same label' },
                        ],
                    },
                ],
            }
            const node = buildBIQuery(config)!.node
            renderDataVisualization({
                query: { ...node, kind: NodeKind.BIVisualizationNode, config },
                response: {
                    columns: ['region', 'sum_amount'],
                    types: [
                        ['region', 'String'],
                        ['sum_amount', 'Float64'],
                    ],
                    results: [
                        ['east', 10],
                        ['west', 20],
                    ],
                },
            })
            await screen.findByLabelText(/chart with/i)
            await waitFor(() => expect(getChart().yTicks()).toEqual(['Same label', 'Same label']))
        })

        it.each([
            { name: 'grouped', display: ChartDisplayType.ActionsBar, extra: {} },
            { name: 'horizontal', display: ChartDisplayType.ActionsBarValue, extra: {} },
            { name: 'stacked', display: ChartDisplayType.ActionsStackedBar, extra: {} },
            {
                name: 'percent (100% stacked)',
                display: ChartDisplayType.ActionsStackedBar,
                extra: { stackBars100: true },
            },
        ])('renders both series in the $name layout', async ({ display, extra }) => {
            renderBar(display, { yAxis: [{ column: 'a' }, { column: 'b' }], ...extra }, twoSeries())

            await screen.findByLabelText(/chart with 2 data series/i)
            await waitFor(() => expect(getChart().yTicks().length).toBeGreaterThan(0))
        })

        it('renders category labels on the vertical axis for horizontal bars', async () => {
            renderBar(
                ChartDisplayType.ActionsBarValue,
                { yAxis: [{ column: 'a', settings: { formatting: { prefix: '$' } } }] },
                barFixture([{ name: 'a', valueAt: (i) => (i + 1) * 1000 }])
            )

            await screen.findByLabelText(/chart with/i)
            await waitFor(() => expect(getChart().xTicks().length).toBeGreaterThan(0))
            expect(getChart().yTicks()).toContain('Oct 1, 2025')
            expect(
                getChart()
                    .xTicks()
                    .map((tick) => tick.startsWith('$'))
            ).not.toContain(false)
        })

        it('renders percentage y-axis ticks for the 100%-stacked layout', async () => {
            renderBar(
                ChartDisplayType.ActionsStackedBar,
                { yAxis: [{ column: 'a' }, { column: 'b' }], stackBars100: true },
                twoSeries()
            )

            await screen.findByLabelText(/chart with 2 data series/i)
            await waitFor(() => expect(getChart().yTicks().length).toBeGreaterThan(0))
            for (const tick of getChart().yTicks()) {
                expect(tick).toMatch(/%$/)
            }
        })
    })

    describe('dual y-axis', () => {
        it.each([
            { name: 'grouped', display: ChartDisplayType.ActionsBar },
            { name: 'stacked', display: ChartDisplayType.ActionsStackedBar },
        ])('renders a right gutter formatted from its own column in the $name layout', async ({ display }) => {
            renderBar(
                display,
                {
                    yAxis: [
                        { column: 'a', settings: { formatting: { prefix: '$' } } },
                        {
                            column: 'b',
                            settings: { formatting: { suffix: '%' }, display: { yAxisPosition: 'right' } },
                        },
                    ],
                },
                twoSeries()
            )

            await screen.findByLabelText(/chart with 2 data series/i)
            await waitFor(() => expect(getChart().hasRightAxis).toBe(true))
            const chart = getChart()
            expect(chart.yTicks().length).toBeGreaterThan(0)
            expect(chart.yTicks().every((tick) => tick.startsWith('$'))).toBe(true)
            const rightTicks = chart.yRightTicks()
            expect(rightTicks.length).toBeGreaterThan(0)
            expect(rightTicks.every((tick) => tick.endsWith('%'))).toBe(true)
        })

        it('renders the axis on the right when the only series targets the right axis', async () => {
            renderBar(
                ChartDisplayType.ActionsBar,
                { yAxis: [{ column: 'a', settings: { display: { yAxisPosition: 'right' } } }] },
                barFixture([{ name: 'a', valueAt: (i) => (i + 1) * 100 }])
            )

            await screen.findByLabelText(/chart with/i)
            await waitFor(() => expect(getChart().yRightTicks().length).toBeGreaterThan(0))
            expect(getChart().yTicks()).toHaveLength(0)
        })
    })

    describe('tooltip', () => {
        // Grouped/stacked bars split the band, so a band-center hover only deterministically lands on
        // a single bar — assert tooltip content with one series, layout/legend with two.
        it('shows the value, swatch, and x-label for a single series', async () => {
            renderBar(
                ChartDisplayType.ActionsBar,
                { yAxis: [{ column: 'a' }] },
                barFixture([{ name: 'a', valueAt: (i) => (i + 1) * 1000 }])
            )

            await screen.findByLabelText(/chart with/i)
            const tooltip = await sqlChart.hoverTooltip(HOVER)

            // formatSqlSeriesValue output — matches the line/combo tooltips, not toLocaleString.
            expect(tooltip.value('a')).toBe('3000')
            expect(tooltip.label()).toBe('Dec 1, 2025')
            expect(tooltip.swatchColors()).toHaveLength(1)
        })
    })

    describe('legend', () => {
        const getLegend = (container: HTMLElement): HTMLElement =>
            container.querySelector<HTMLElement>('[data-attr="hog-chart-timeseries-bar-legend"]')!

        it('renders an in-chart legend listing every series when showLegend is set', async () => {
            const { container } = renderBar(
                ChartDisplayType.ActionsStackedBar,
                { yAxis: [{ column: 'a' }, { column: 'b' }], showLegend: true },
                twoSeries()
            )

            await screen.findByLabelText(/chart with 2 data series/i)
            const labels = [...getLegend(container).querySelectorAll('button')].map((b) => b.textContent)
            expect(labels).toEqual(['a', 'b'])
        })

        it('hides a series when its legend item is toggled off', async () => {
            const { container } = renderBar(
                ChartDisplayType.ActionsStackedBar,
                { yAxis: [{ column: 'a' }, { column: 'b' }], showLegend: true },
                twoSeries()
            )

            await screen.findByLabelText(/chart with 2 data series/i)
            const bButton = [...getLegend(container).querySelectorAll('button')].find((b) =>
                b.textContent?.includes('b')
            )!
            fireEvent.click(bButton)

            await waitFor(() => expect(getChart().seriesCount).toBe(1))
        })
    })

    describe('goal lines', () => {
        it.each([
            [ChartDisplayType.ActionsBar, 'horizontal'],
            [ChartDisplayType.ActionsBarValue, 'vertical'],
        ] as const)('renders a goal line on the value axis for %s', async (display, orientation) => {
            renderBar(
                display,
                { yAxis: [{ column: 'a' }], goalLines: [{ label: 'Target', value: 250, displayIfCrossed: true }] },
                barFixture([{ name: 'a', valueAt: (i) => (i + 1) * 100 }])
            )

            await screen.findByLabelText(/chart with/i)
            const lines = getChart().referenceLines()
            expect(lines.map((l) => l.label)).toEqual(['Target'])
            expect(lines[0].orientation).toBe(orientation)
        })
    })
})
