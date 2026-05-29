import { fireEvent, waitFor } from '@testing-library/react'

import { RADIAL_MARGINS } from '../../core/RadialChart'
import type { ChartTheme, Series } from '../../core/types'
import { getHogChartTooltip, renderHogChart, waitForHogChartTooltip } from '../../testing'
import { dimensions } from '../../testing/jsdom'
import { PieChart } from './PieChart'

const THEME: ChartTheme = {
    colors: ['#1f77b4', '#ff7f0e', '#2ca02c'],
    backgroundColor: '#ffffff',
}

const THREE_SERIES: Series[] = [
    { key: 'a', label: 'A', data: [10] },
    { key: 'b', label: 'B', data: [10] },
    { key: 'c', label: 'C', data: [10] },
]

// The radial chart computes its own plot box from `RADIAL_MARGINS`; the shared `dimensions`
// fixture uses `DEFAULT_MARGINS`, so we mirror the radial geometry locally to derive
// hover coordinates. Mirrors `computePieLayout`'s radiusPadding default.
const RADIAL_RADIUS_PADDING = 0.92
const PLOT_WIDTH = dimensions.width - RADIAL_MARGINS.left - RADIAL_MARGINS.right
const PLOT_HEIGHT = dimensions.height - RADIAL_MARGINS.top - RADIAL_MARGINS.bottom
const CX = RADIAL_MARGINS.left + PLOT_WIDTH / 2
const CY = RADIAL_MARGINS.top + PLOT_HEIGHT / 2
const OUTER_RADIUS = (Math.min(PLOT_WIDTH, PLOT_HEIGHT) / 2) * RADIAL_RADIUS_PADDING
const MID_RADIUS = OUTER_RADIUS / 2 // innerRadius = 0 for a non-donut pie

function sliceCentroidCoords(sliceIndex: number, totalSlices: number): { clientX: number; clientY: number } {
    const sliceAngle = (2 * Math.PI) / totalSlices
    const centroid = sliceIndex * sliceAngle + sliceAngle / 2
    return {
        clientX: CX + Math.sin(centroid) * MID_RADIUS,
        clientY: CY - Math.cos(centroid) * MID_RADIUS,
    }
}

function hoverSlice(wrapper: HTMLElement, sliceIndex: number, totalSlices: number): void {
    fireEvent.mouseMove(wrapper, sliceCentroidCoords(sliceIndex, totalSlices))
}

function sliceLabels(wrapper: HTMLElement): HTMLElement[] {
    return Array.from(wrapper.querySelectorAll<HTMLElement>('[data-attr="hog-chart-pie-slice-label"]'))
}

describe('PieChart', () => {
    it('renders one on-slice label per slice when all are above the threshold', () => {
        const { chart } = renderHogChart(<PieChart series={THREE_SERIES} theme={THEME} />)
        expect(sliceLabels(chart.element)).toHaveLength(3)
    })

    it('forwards `dataAttr` to the chart wrapper', () => {
        const { chart } = renderHogChart(<PieChart series={THREE_SERIES} theme={THEME} dataAttr="pie-instance" />)
        expect(chart.element.getAttribute('data-attr')).toBe('pie-instance')
    })

    it('renders the optional centerLabel inside the chart wrapper', () => {
        const { chart } = renderHogChart(
            <PieChart series={THREE_SERIES} theme={THEME} centerLabel={<span data-attr="pie-center">Total</span>} />
        )
        expect(chart.element.querySelector('[data-attr="pie-center"]')?.textContent).toBe('Total')
    })

    it('omits excluded series from the on-slice labels', () => {
        const series: Series[] = [
            { key: 'a', label: 'A', data: [10] },
            { key: 'b', label: 'B', data: [10], visibility: { excluded: true } },
            { key: 'c', label: 'C', data: [10] },
        ]
        const { chart } = renderHogChart(<PieChart series={series} theme={THEME} />)
        const labels = sliceLabels(chart.element).map((el) => el.textContent ?? '')
        // Each slice contributes a value-only label by default; 2 visible slices => 2 labels.
        expect(labels).toHaveLength(2)
    })

    it('renders empty state when no series have positive values', () => {
        const series: Series[] = [{ key: 'a', label: 'A', data: [0] }]
        const { chart } = renderHogChart(<PieChart series={series} theme={THEME} />)
        // No slices means no on-slice labels and no thrown errors.
        expect(sliceLabels(chart.element)).toHaveLength(0)
    })

    it('formats slice values as percentages when isPercent is set', () => {
        const series: Series[] = [
            { key: 'a', label: 'A', data: [25] },
            { key: 'b', label: 'B', data: [75] },
        ]
        const { chart } = renderHogChart(<PieChart series={series} theme={THEME} config={{ isPercent: true }} />)
        const text = sliceLabels(chart.element)
            .map((el) => el.textContent ?? '')
            .join('|')
        expect(text).toContain('25%')
        expect(text).toContain('75%')
    })

    it('uses the provided valueFormatter for on-slice values', () => {
        const series: Series[] = [{ key: 'a', label: 'A', data: [1500] }]
        const { chart } = renderHogChart(
            <PieChart series={series} theme={THEME} valueFormatter={(v) => `$${(v / 1000).toFixed(1)}k`} />
        )
        expect(sliceLabels(chart.element)[0].textContent).toContain('$1.5k')
    })

    describe('tooltip', () => {
        it('exposes the hovered slice via the structured TooltipContext', async () => {
            const { chart } = renderHogChart(<PieChart series={THREE_SERIES} theme={THEME} />)
            hoverSlice(chart.element, 0, THREE_SERIES.length)
            const tooltip = await chart.waitForTooltip()
            expect(tooltip.label).toBe('A')
            expect(tooltip.seriesData).toHaveLength(1)
            expect(tooltip.seriesData[0].series.key).toBe('a')
            expect(tooltip.seriesData[0].value).toBe(10)
            expect(tooltip.seriesData[0].fraction).toBeCloseTo(1 / 3, 5)
        })

        it('renders the default PieTooltip with label, value, and percent share', async () => {
            const { chart } = renderHogChart(<PieChart series={THREE_SERIES} theme={THEME} />, { nativeTooltip: true })
            hoverSlice(chart.element, 1, THREE_SERIES.length)
            const tooltipEl = await waitForHogChartTooltip()
            expect(tooltipEl.textContent).toContain('B')
            expect(tooltipEl.textContent).toContain('10')
            expect(tooltipEl.textContent).toContain('33.3%')
        })

        it('passes through to a user-supplied tooltip render prop', async () => {
            const userTooltip = jest.fn((): React.ReactElement => <div data-attr="custom-pie-tooltip">custom</div>)
            const { chart } = renderHogChart(
                <PieChart series={THREE_SERIES} theme={THEME} tooltip={userTooltip} />,
                { nativeTooltip: true }
            )
            hoverSlice(chart.element, 0, THREE_SERIES.length)
            const tooltipEl = await waitForHogChartTooltip()
            expect(tooltipEl.querySelector('[data-attr="custom-pie-tooltip"]')).not.toBeNull()
            expect(userTooltip).toHaveBeenCalled()
        })

        it('suppresses the tooltip when config.tooltip.enabled is false', () => {
            const { chart } = renderHogChart(
                <PieChart series={THREE_SERIES} theme={THEME} config={{ tooltip: { enabled: false } }} />
            )
            hoverSlice(chart.element, 0, THREE_SERIES.length)
            // No tooltip portal should appear — assert synchronously since the chart short-circuits.
            expect(getHogChartTooltip()).toBeNull()
        })
    })

    describe('click', () => {
        it('invokes onSliceClick with the clicked slice payload', async () => {
            const onSliceClick = jest.fn()
            const { chart } = renderHogChart(
                <PieChart series={THREE_SERIES} theme={THEME} onSliceClick={onSliceClick} />
            )
            hoverSlice(chart.element, 2, THREE_SERIES.length)
            // Wait for the hover lifecycle to settle so the click handler sees the right slice.
            await chart.waitForTooltip()
            fireEvent.click(chart.element)
            await waitFor(() => expect(onSliceClick).toHaveBeenCalled())
            const arg = onSliceClick.mock.calls[0][0]
            expect(arg.sliceIndex).toBe(2)
            expect(arg.series.key).toBe('c')
            expect(arg.value).toBe(10)
            expect(arg.fraction).toBeCloseTo(1 / 3, 5)
        })

        it('does not invoke onSliceClick when the cursor is outside the ring', () => {
            const onSliceClick = jest.fn()
            const { chart } = renderHogChart(
                <PieChart series={THREE_SERIES} theme={THEME} onSliceClick={onSliceClick} />
            )
            // Far corner — well past `outerRadius` — so `sliceAt` returns -1 and the click
            // handler early-returns without invoking `onSliceClick`.
            fireEvent.mouseMove(chart.element, { clientX: 0, clientY: 0 })
            fireEvent.click(chart.element)
            expect(onSliceClick).not.toHaveBeenCalled()
        })
    })

    describe('hover offset', () => {
        it('skips the pop-out repaint when disableHoverOffset is true (no crash)', () => {
            const { chart } = renderHogChart(
                <PieChart series={THREE_SERIES} theme={THEME} config={{ disableHoverOffset: true }} />
            )
            // No tooltip assertions here — this is purely a smoke test that the drawHover guard
            // returns early when effective hover offset is 0.
            hoverSlice(chart.element, 0, THREE_SERIES.length)
            expect(sliceLabels(chart.element)).toHaveLength(3)
        })
    })

    describe('error handling', () => {
        let consoleErrorSpy: jest.SpyInstance
        beforeEach(() => {
            consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {})
        })
        afterEach(() => {
            consoleErrorSpy.mockRestore()
        })

        it('reports tooltip render errors through onError', async () => {
            const onError = jest.fn()
            const tooltip = (): React.ReactNode => {
                throw new Error('boom')
            }
            const { chart } = renderHogChart(
                <PieChart series={THREE_SERIES} theme={THEME} tooltip={tooltip} onError={onError} />
            )
            hoverSlice(chart.element, 0, THREE_SERIES.length)
            await waitFor(() => expect(onError).toHaveBeenCalled())
        })
    })

    describe('children', () => {
        it('renders custom overlay children inside the chart wrapper', () => {
            const { chart } = renderHogChart(
                <PieChart series={THREE_SERIES} theme={THEME}>
                    <div data-attr="custom-pie-child" />
                </PieChart>
            )
            expect(chart.element.querySelector('[data-attr="custom-pie-child"]')).not.toBeNull()
        })
    })
})
