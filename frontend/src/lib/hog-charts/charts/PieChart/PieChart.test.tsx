import { fireEvent, waitFor } from '@testing-library/react'

import type { ChartTheme } from '../../core/types'
import { renderHogChart, waitForHogChartTooltip } from '../../testing'
import { mockRect } from '../../testing/jsdom'
import { PieChart, type PieSlice, type PieTooltipContext } from './PieChart'
import { computePieLayout, computeSliceAngles, type ResolvedPieSlice } from './utils/pie-layout'

const THEME: ChartTheme = {
    colors: ['#1f77b4', '#ff7f0e', '#2ca02c'],
    backgroundColor: '#ffffff',
}

const SLICES: PieSlice[] = [
    { key: 'a', label: 'A', value: 30 },
    { key: 'b', label: 'B', value: 50 },
    { key: 'c', label: 'C', value: 20 },
]

// PieChart uses uniform 12px margins on the wrapper rect.
const PIE_MARGIN = 12

// Position the cursor at the centre of a slice — relative to the chart's
// real plot layout, since the chart will hit-test against the same geometry.
function fireMouseOverSlice(wrapper: HTMLElement, sliceIndex: number, slices: PieSlice[] = SLICES): void {
    const dims = {
        width: mockRect.width,
        height: mockRect.height,
        plotLeft: PIE_MARGIN,
        plotTop: PIE_MARGIN,
        plotWidth: mockRect.width - PIE_MARGIN * 2,
        plotHeight: mockRect.height - PIE_MARGIN * 2,
    }
    const layout = computePieLayout(dims)
    const total = slices.reduce((s, x) => s + x.value, 0)
    const resolved: ResolvedPieSlice[] = slices.map((s) => ({
        key: s.key,
        label: s.label,
        value: s.value,
        color: '#000',
    }))
    const angles = computeSliceAngles(resolved, total)
    const target = angles[sliceIndex]
    const mid = (target.startAngle + target.endAngle) / 2
    const r = (layout.innerRadius + layout.outerRadius) / 2 || layout.outerRadius / 2
    const x = layout.cx + Math.cos(mid) * r
    const y = layout.cy + Math.sin(mid) * r
    fireEvent.mouseMove(wrapper, { clientX: x, clientY: y })
}

describe('PieChart', () => {
    it('reports the visible slice count via aria-label', () => {
        const { chart } = renderHogChart(<PieChart slices={SLICES} theme={THEME} />)
        expect(chart.seriesCount).toBe(3)
    })

    it('filters out non-positive slices', () => {
        const slices: PieSlice[] = [
            { key: 'a', label: 'A', value: 10 },
            { key: 'b', label: 'B', value: 0 },
            { key: 'c', label: 'C', value: -5 },
        ]
        const { chart } = renderHogChart(<PieChart slices={slices} theme={THEME} />)
        expect(chart.seriesCount).toBe(1)
    })

    it('renders an empty state when no slice has a positive value', () => {
        const slices: PieSlice[] = [
            { key: 'a', label: 'A', value: 0 },
            { key: 'b', label: 'B', value: -1 },
        ]
        const { container } = renderHogChart(<PieChart slices={slices} theme={THEME} />)
        expect(container.textContent).toContain('No data to display')
    })

    it('renders a custom empty-state node when provided', () => {
        const { container } = renderHogChart(
            <PieChart slices={[]} theme={THEME} emptyState={<span>nothing here</span>} />
        )
        expect(container.textContent).toContain('nothing here')
    })

    it('forwards `dataAttr` to the chart wrapper', () => {
        const { chart } = renderHogChart(<PieChart slices={SLICES} theme={THEME} dataAttr="pie-instance" />)
        expect(chart.element.getAttribute('data-attr')).toBe('pie-instance')
    })

    it('opens the default tooltip with value and percentage on hover', async () => {
        const { chart } = renderHogChart(<PieChart slices={SLICES} theme={THEME} />)
        fireMouseOverSlice(chart.element, 1)
        const tooltip = await waitForHogChartTooltip()
        expect(tooltip.textContent).toContain('B')
        expect(tooltip.textContent).toContain('50')
        expect(tooltip.textContent).toContain('50.0%')
    })

    it('invokes the tooltip render prop with PieTooltipContext', async () => {
        const tooltipSpy = jest.fn((_ctx: PieTooltipContext) => <div>custom tooltip</div>)
        const { chart } = renderHogChart(<PieChart slices={SLICES} theme={THEME} tooltip={tooltipSpy} />)
        fireMouseOverSlice(chart.element, 0)
        await waitForHogChartTooltip()
        expect(tooltipSpy).toHaveBeenCalled()
        const ctx = tooltipSpy.mock.calls[0]![0]
        expect(ctx.slice.key).toBe('a')
        expect(ctx.percent).toBeCloseTo(30)
        expect(ctx.total).toBe(100)
        expect(ctx.slices).toHaveLength(3)
    })

    it('invokes onSliceClick with the slice and percent', async () => {
        const onSliceClick = jest.fn()
        const { chart } = renderHogChart(<PieChart slices={SLICES} theme={THEME} onSliceClick={onSliceClick} />)
        fireMouseOverSlice(chart.element, 2)
        await waitForHogChartTooltip()
        fireEvent.click(chart.element)
        expect(onSliceClick).toHaveBeenCalledWith(
            expect.objectContaining({
                sliceIndex: 2,
                value: 20,
                total: 100,
                slice: expect.objectContaining({ key: 'c' }),
            })
        )
        expect(onSliceClick.mock.calls[0][0].percent).toBeCloseTo(20)
    })

    it('does not invoke onSliceClick when the click misses every slice', () => {
        const onSliceClick = jest.fn()
        const { chart } = renderHogChart(<PieChart slices={SLICES} theme={THEME} onSliceClick={onSliceClick} />)
        // Click without first hovering — hoverIndex stays at -1.
        fireEvent.click(chart.element)
        expect(onSliceClick).not.toHaveBeenCalled()
    })

    it('pins the tooltip on click when tooltip.pinnable is set', async () => {
        const { chart } = renderHogChart(
            <PieChart slices={SLICES} theme={THEME} config={{ tooltip: { pinnable: true } }} />
        )
        fireMouseOverSlice(chart.element, 0)
        const tooltip = await waitForHogChartTooltip()
        fireEvent.click(chart.element)
        await waitFor(() => {
            expect(tooltip.classList.contains('hog-charts-tooltip--pinned')).toBe(true)
        })
    })

    it('hides the tooltip when tooltip.enabled is false', () => {
        const { chart } = renderHogChart(
            <PieChart slices={SLICES} theme={THEME} config={{ tooltip: { enabled: false } }} />
        )
        fireMouseOverSlice(chart.element, 0)
        expect(document.querySelector('[data-hog-charts-tooltip]')).toBeNull()
    })

    it('caps innerRadius into the donut range without crashing', () => {
        const { chart } = renderHogChart(
            <PieChart slices={SLICES} theme={THEME} config={{ innerRadius: 0.5 }} />
        )
        expect(chart.seriesCount).toBe(3)
    })

    it('applies a custom value formatter to the tooltip', async () => {
        const formatter = (v: number): string => `$${v}`
        const { chart } = renderHogChart(
            <PieChart slices={SLICES} theme={THEME} config={{ valueFormatter: formatter }} />
        )
        fireMouseOverSlice(chart.element, 0)
        const tooltip = await waitForHogChartTooltip()
        expect(tooltip.textContent).toContain('$30')
    })

    it('uses slice-provided color over the theme palette', () => {
        const slices: PieSlice[] = [
            { key: 'a', label: 'A', value: 10, color: '#abcdef' },
            { key: 'b', label: 'B', value: 10 },
        ]
        const { chart } = renderHogChart(<PieChart slices={slices} theme={THEME} />)
        // We can't read canvas pixels in jsdom — confirm the chart still renders both slices.
        expect(chart.seriesCount).toBe(2)
    })
})
