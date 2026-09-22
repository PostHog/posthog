import { act, fireEvent, waitFor } from '@testing-library/react'

import type { ChartMargins, ChartTheme } from '../../core/types'
import {
    createDefaultTooltipAccessor,
    getHogChartTooltip,
    rawDrag,
    renderHogChart,
    waitForHogChartTooltip,
} from '../../testing'
import { ScatterChart } from './ScatterChart'
import type { ScatterAreaSelection, ScatterChartConfig, ScatterPointDatum, ScatterSeries } from './types'

const THEME: ChartTheme = {
    colors: ['#1f77b4', '#ff7f0e'],
    backgroundColor: '#ffffff',
    gridColor: '#eeeeee',
}

// Zeroed margins make the plot the whole 800×400 jsdom canvas, so a data coordinate maps to a
// client pixel the test can compute exactly.
const MARGINS: Partial<ChartMargins> = { top: 0, right: 0, bottom: 0, left: 0 }
const PLOT_WIDTH = 800
const PLOT_HEIGHT = 400
/** Both axes span 0–100 across every fixture below, so `nice()` leaves the domain alone. */
const clientX = (x: number): number => (x / 100) * PLOT_WIDTH
const clientY = (y: number): number => PLOT_HEIGHT - (y / 100) * PLOT_HEIGHT

const SERIES: ScatterSeries[] = [
    {
        key: 'reads',
        label: 'Reads',
        points: [
            { x: 0, y: 0, label: 'Bottom left' },
            { x: 100, y: 100, label: 'Top right' },
            // Off the diagonal, so a tooltip that swapped the two axes couldn't still read correctly.
            { x: 25, y: 80, label: 'Off diagonal' },
        ],
    },
    { key: 'writes', label: 'Writes', points: [{ x: 0, y: 100, label: 'Top left' }] },
]

function renderScatter(
    props: Partial<React.ComponentProps<typeof ScatterChart>> = {}
): ReturnType<typeof renderHogChart> {
    return renderHogChart(
        <ScatterChart
            series={SERIES}
            theme={THEME}
            config={{ margins: MARGINS, xAxis: { label: 'Reads' }, yAxis: { label: 'Writes' }, ...props.config }}
            {...props}
        />,
        { nativeTooltip: true }
    )
}

/** Hover a data coordinate, re-dispatching until the chart has committed its scales. */
async function hoverPoint(wrapper: HTMLElement, x: number, y: number): Promise<HTMLElement> {
    return waitForHogChartTooltip(3000, () => {
        act(() => {
            fireEvent.mouseMove(wrapper, { clientX: clientX(x), clientY: clientY(y) })
        })
    })
}

describe('ScatterChart', () => {
    it('ticks each axis over its own value range, not once per point', () => {
        const { chart } = renderScatter()
        expect(chart.xTicks()).toContain('100')
        expect(chart.xAxisLabel()).toBe('Reads')
    })

    it('reads a hovered point as both of its coordinates', async () => {
        const { chart } = renderScatter()
        const tooltip = createDefaultTooltipAccessor(await hoverPoint(chart.element, 25, 80))
        expect(tooltip.label()).toBe('Off diagonal')
        expect(tooltip.value('Reads')).toBe('25')
        expect(tooltip.value('Writes')).toBe('80')
    })

    it('names the y row after the series when the y axis is untitled, without repeating it as a header', async () => {
        const { chart } = renderScatter({
            series: [
                {
                    key: 'writes',
                    label: 'Writes',
                    points: [
                        { x: 0, y: 0 },
                        { x: 25, y: 80 },
                        { x: 100, y: 100 },
                    ],
                },
            ],
            config: { margins: MARGINS, xAxis: { label: 'Reads' } },
        })
        const tooltip = createDefaultTooltipAccessor(await hoverPoint(chart.element, 25, 80))
        expect(tooltip.value('Writes')).toBe('80')
        expect(tooltip.label()).toBe('')
    })

    it.each<[string, ScatterChartConfig, string, string[]]>([
        [
            'pins each axis to a caller domain',
            { xAxis: { domain: [0, 50] }, yAxis: { domain: [0, 50] } },
            '50',
            ['100'],
        ],
        [
            'falls back to linear when a log domain starts at a non-positive bound',
            { xAxis: { scaleType: 'log', domain: [0, 100] }, yAxis: { scaleType: 'log', domain: [0, 100] } },
            '100',
            [],
        ],
    ])('%s', (_, config, expected, absent) => {
        const { chart } = renderScatter({ config: { margins: MARGINS, ...config } })
        // Asserted on both axes, so a scale built against the wrong axis fails too.
        for (const ticks of [chart.xTicks(), chart.yTicks()]) {
            expect(ticks).toContain(expected)
            expect(ticks.filter((tick) => absent.includes(tick))).toEqual([])
        }
    })

    it('drops a point outside a pinned domain rather than clamping it onto the plot edge', async () => {
        const series: ScatterSeries[] = [
            {
                key: 'latency',
                label: 'Latency',
                points: [
                    { x: 10, y: 10, label: 'In range' },
                    { x: 10, y: 1000, label: 'Above the domain' },
                ],
            },
        ]
        const { chart } = renderHogChart(
            <ScatterChart
                series={series}
                theme={THEME}
                config={{
                    margins: MARGINS,
                    xAxis: { domain: [0, 100] },
                    yAxis: { scaleType: 'log', domain: [1, 100] },
                }}
            />,
            { nativeTooltip: true }
        )
        // A log scale clamps, so the excluded point would otherwise sit hoverable on the top edge.
        await waitForHogChartTooltip(3000, () => {
            act(() => {
                fireEvent.mouseMove(chart.element, { clientX: clientX(10), clientY: PLOT_HEIGHT / 2 })
            })
        })
        act(() => {
            fireEvent.mouseMove(chart.element, { clientX: clientX(10), clientY: 4 })
        })
        await waitFor(() => expect(getHogChartTooltip()).toBeNull())
    })

    it('drops a legend-hidden series from the plot, not just from the legend', async () => {
        const { chart } = renderScatter({ config: { margins: MARGINS, legend: { hiddenKeys: ['writes'] } } })
        // Hover a visible point first, or an absent tooltip passes on uncommitted scales alone.
        await hoverPoint(chart.element, 100, 100)
        act(() => {
            fireEvent.mouseMove(chart.element, { clientX: clientX(0), clientY: clientY(100) })
        })
        await waitFor(() => expect(getHogChartTooltip()).toBeNull())
    })

    it('reports the clicked point with its series and consumer meta', async () => {
        const onPointClick = jest.fn()
        const series: ScatterSeries<{ orgId: string }>[] = [
            { key: 'orgs', label: 'Orgs', points: [{ x: 100, y: 100, label: 'Hedgebox', meta: { orgId: 'hb' } }] },
        ]
        const { chart } = renderHogChart(
            <ScatterChart series={series} theme={THEME} config={{ margins: MARGINS }} onPointClick={onPointClick} />,
            { nativeTooltip: true }
        )
        await hoverPoint(chart.element, 100, 100)
        fireEvent.click(chart.element)

        expect(onPointClick).toHaveBeenCalledTimes(1)
        expect(onPointClick.mock.calls[0][0]).toMatchObject<Partial<ScatterPointDatum<{ orgId: string }>>>({
            x: 100,
            y: 100,
            label: 'Hedgebox',
            seriesKey: 'orgs',
            seriesLabel: 'Orgs',
            pointIndex: 0,
            meta: { orgId: 'hb' },
        })
    })

    it.each<[string, { x: number; y: number }, ScatterAreaSelection]>([
        ['in the points own units, not pixels', { x: 60, y: 30 }, { x: [20, 60], y: [30, 80] }],
        // Brushing into a corner routinely leaves the plot, where an unclamped pixel inverts to a
        // range wider than the rectangle the user saw.
        ['clamped to each axis when the drag overshoots the plot', { x: -30, y: 130 }, { x: [0, 20], y: [80, 100] }],
    ])('reports a drag selection %s', async (_, to, expected) => {
        const onAreaSelect = jest.fn()
        const { chart } = renderScatter({ onAreaSelect })
        await hoverPoint(chart.element, 100, 100)

        rawDrag(chart.element, {
            from: { x: clientX(20), y: clientY(80) },
            to: { x: clientX(to.x), y: clientY(to.y) },
        })

        expect(onAreaSelect).toHaveBeenCalledTimes(1)
        const selection = onAreaSelect.mock.calls[0][0] as ScatterAreaSelection
        expect(selection.x[0]).toBeCloseTo(expected.x[0])
        expect(selection.x[1]).toBeCloseTo(expected.x[1])
        expect(selection.y[0]).toBeCloseTo(expected.y[0])
        expect(selection.y[1]).toBeCloseTo(expected.y[1])
    })
})
