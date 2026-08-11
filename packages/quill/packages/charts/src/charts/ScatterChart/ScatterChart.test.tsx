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

// The jsdom mock sizes every element 800×400; zeroing the margins makes the plot area the whole
// canvas, so a data coordinate maps to a client pixel the test can compute exactly.
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
    it.each<[string, ScatterChartConfig | undefined, number]>([
        ['one series per group of points', undefined, 2],
        ['no series for one hidden through the legend', { legend: { hiddenKeys: ['writes'] } }, 1],
    ])('renders %s', (_, config, expected) => {
        const { chart } = renderScatter({ config: { margins: MARGINS, ...config } })
        expect(chart.seriesCount).toBe(expected)
    })

    it('labels the x axis with its own domain, not with one tick per point', () => {
        // Three points would give category ticks '0'–'2'; a continuous axis ticks the data range.
        const { chart } = renderScatter()
        expect(chart.xTicks()).toContain('100')
        expect(chart.xAxisLabel()).toBe('Reads')
    })

    it('renders an empty series list without crashing', () => {
        const { chart } = renderHogChart(<ScatterChart series={[]} theme={THEME} config={{ margins: MARGINS }} />)
        expect(chart.seriesCount).toBe(0)
    })

    it('resolves the hovered point by both axes, not by x alone', async () => {
        // Both points sit at x = 0, so an x-only hit test (what the line and bar charts use)
        // couldn't tell them apart.
        const { chart } = renderScatter()
        const tooltip = createDefaultTooltipAccessor(await hoverPoint(chart.element, 0, 100))
        expect(tooltip.label()).toBe('Top left')
    })

    it('shows both coordinates in the tooltip, titled by the axis labels', async () => {
        const { chart } = renderScatter()
        const tooltip = createDefaultTooltipAccessor(await hoverPoint(chart.element, 100, 100))
        expect(tooltip.label()).toBe('Top right')
        expect(tooltip.value('Reads')).toBe('100')
        expect(tooltip.value('Writes')).toBe('100')
    })

    it('shows nothing when the cursor is over empty plot area', async () => {
        // Hover a real point first: asserting on an absent tooltip would otherwise pass simply
        // because the chart had not committed its scales yet.
        const { chart } = renderScatter()
        await hoverPoint(chart.element, 100, 100)
        act(() => {
            fireEvent.mouseMove(chart.element, { clientX: clientX(50), clientY: clientY(50) })
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

    it('reports a drag selection in data units, not pixels', async () => {
        const onAreaSelect = jest.fn()
        const { chart } = renderScatter({ onAreaSelect })
        await hoverPoint(chart.element, 100, 100)

        rawDrag(chart.element, {
            from: { x: clientX(20), y: clientY(80) },
            to: { x: clientX(60), y: clientY(30) },
        })

        expect(onAreaSelect).toHaveBeenCalledTimes(1)
        const selection = onAreaSelect.mock.calls[0][0] as ScatterAreaSelection
        expect(selection.x[0]).toBeCloseTo(20)
        expect(selection.x[1]).toBeCloseTo(60)
        expect(selection.y[0]).toBeCloseTo(30)
        expect(selection.y[1]).toBeCloseTo(80)
    })
})
