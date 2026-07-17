import { fireEvent, waitFor } from '@testing-library/react'
import React from 'react'

import type { RadialSlicePayload } from '../../core/hooks/useRadialInteraction'
import { RADIAL_MARGINS } from '../../core/RadialChart'
import type { ResolvedSeries, ChartTheme, Series } from '../../core/types'
import { getHogChartTooltip, renderHogChart } from '../../testing'
import { mockRect } from '../../testing/jsdom'
import { computePieLayout } from './computePieLayout'
import type { PieLayout } from './computePieLayout'
import { PieChart } from './PieChart'

const THEME: ChartTheme = {
    colors: ['#1f77b4', '#ff7f0e', '#2ca02c'],
    backgroundColor: '#ffffff',
}

const SERIES: Series[] = [
    { key: 'a', label: 'Chrome', data: [50] },
    { key: 'b', label: 'Firefox', data: [50] },
]

// RadialChart computes its plot box from the full canvas rect minus RADIAL_MARGINS.
const PLOT_BOX = {
    plotLeft: RADIAL_MARGINS.left,
    plotTop: RADIAL_MARGINS.top,
    plotWidth: mockRect.width - RADIAL_MARGINS.left - RADIAL_MARGINS.right,
    plotHeight: mockRect.height - RADIAL_MARGINS.top - RADIAL_MARGINS.bottom,
}

function layoutFor(series: Series[], innerRadiusRatio = 0): PieLayout {
    return computePieLayout({ series: series as ResolvedSeries[], dimensions: PLOT_BOX, innerRadiusRatio })
}

// A cursor point on a slice's centroid bisector at mid-radius — guaranteed inside the slice.
// The wrapper rect is mocked at origin (0,0), so client coords equal cursor offsets.
function pointInSlice(layout: PieLayout, sliceIndex: number): { clientX: number; clientY: number } {
    const slice = layout.slices[sliceIndex]
    const midR = (layout.innerRadius + layout.outerRadius) / 2
    return {
        clientX: layout.cx + Math.sin(slice.centroidAngle) * midR,
        clientY: layout.cy - Math.cos(slice.centroidAngle) * midR,
    }
}

function sliceLabels(wrapper: HTMLElement): string[] {
    return Array.from(wrapper.querySelectorAll<HTMLElement>('[data-attr="hog-chart-pie-slice-label"]')).map(
        (el) => el.textContent ?? ''
    )
}

describe('PieChart', () => {
    it('renders a canvas labeled as a pie chart with one slice per series', () => {
        const { container } = renderHogChart(<PieChart series={SERIES} theme={THEME} />)
        const canvas = container.querySelector('canvas[aria-label]')
        expect(canvas?.getAttribute('aria-label')).toBe('Pie chart with 2 slices')
    })

    it('forwards dataAttr to the chart wrapper', () => {
        const { chart } = renderHogChart(<PieChart series={SERIES} theme={THEME} dataAttr="pie-instance" />)
        expect(chart.element.getAttribute('data-attr')).toBe('pie-instance')
    })

    it('renders one on-slice value label per slice by default', () => {
        const { chart } = renderHogChart(<PieChart series={SERIES} theme={THEME} />)
        const labels = sliceLabels(chart.element)
        expect(labels).toHaveLength(2)
        expect(labels.join('|')).toContain('50')
    })

    it('renders percentage labels when isPercent is set', () => {
        const { chart } = renderHogChart(<PieChart series={SERIES} theme={THEME} config={{ isPercent: true }} />)
        const text = sliceLabels(chart.element).join('|')
        expect(text).toContain('50%')
    })

    it('suppresses on-slice value labels when showValueOnSlice is false', () => {
        const { chart } = renderHogChart(
            <PieChart series={SERIES} theme={THEME} config={{ showValueOnSlice: false }} />
        )
        expect(sliceLabels(chart.element)).toHaveLength(0)
    })

    it('renders a center label for a donut', () => {
        const { chart } = renderHogChart(
            <PieChart series={SERIES} theme={THEME} config={{ innerRadiusRatio: 0.5 }} centerLabel="Total: 100" />
        )
        expect(chart.element.textContent).toContain('Total: 100')
    })

    it('renders custom overlay children', () => {
        const { chart } = renderHogChart(
            <PieChart series={SERIES} theme={THEME}>
                <div data-attr="custom-child" />
            </PieChart>
        )
        expect(chart.element.querySelector('[data-attr="custom-child"]')).not.toBeNull()
    })

    it('renders an empty pie (zero total) without crashing and with no slice labels', () => {
        const { chart } = renderHogChart(<PieChart series={[{ key: 'a', label: 'A', data: [0] }]} theme={THEME} />)
        expect(sliceLabels(chart.element)).toHaveLength(0)
    })

    describe('hover & tooltip', () => {
        it('shows a tooltip for the slice under the cursor', async () => {
            const { chart } = renderHogChart(<PieChart series={SERIES} theme={THEME} />)
            const layout = layoutFor(SERIES)
            fireEvent.mouseMove(chart.element, pointInSlice(layout, 0))
            const tooltip = await chart.waitForTooltip()
            expect(tooltip.seriesData[0].series.label).toBe('Chrome')
            expect(tooltip.seriesData[0].value).toBe(50)
        })

        it('switches the tooltip to the other slice when the cursor moves', async () => {
            const { chart } = renderHogChart(<PieChart series={SERIES} theme={THEME} />)
            const layout = layoutFor(SERIES)
            fireEvent.mouseMove(chart.element, pointInSlice(layout, 1))
            const tooltip = await chart.waitForTooltip()
            expect(tooltip.seriesData[0].series.label).toBe('Firefox')
        })

        it('shows no tooltip when hovering the donut hole', async () => {
            const { chart } = renderHogChart(
                <PieChart series={SERIES} theme={THEME} config={{ innerRadiusRatio: 0.5 }} />
            )
            const layout = layoutFor(SERIES, 0.5)
            // Dead center is inside the inner radius — a hit-test miss.
            fireEvent.mouseMove(chart.element, { clientX: layout.cx, clientY: layout.cy })
            await new Promise((resolve) => setTimeout(resolve, 0))
            expect(getHogChartTooltip()?.textContent ?? '').toBe('')
        })
    })

    describe('slice click', () => {
        it('invokes onSliceClick with the clicked slice payload', async () => {
            const onSliceClick = jest.fn<void, [RadialSlicePayload]>()
            const { chart } = renderHogChart(<PieChart series={SERIES} theme={THEME} onSliceClick={onSliceClick} />)
            const layout = layoutFor(SERIES)
            fireEvent.mouseMove(chart.element, pointInSlice(layout, 1))
            await waitFor(() => expect(getHogChartTooltip()).not.toBeNull())
            fireEvent.click(chart.element)
            expect(onSliceClick).toHaveBeenCalledWith(
                expect.objectContaining({ sliceIndex: 1, value: 50, fraction: 0.5 })
            )
            expect(onSliceClick.mock.calls[0][0].series.key).toBe('b')
        })

        it('does not invoke onSliceClick when the click misses every slice', () => {
            const onSliceClick = jest.fn()
            const { chart } = renderHogChart(
                <PieChart
                    series={SERIES}
                    theme={THEME}
                    config={{ innerRadiusRatio: 0.5 }}
                    onSliceClick={onSliceClick}
                />
            )
            const layout = layoutFor(SERIES, 0.5)
            // Hover the hole (miss), then click — nothing should fire.
            fireEvent.mouseMove(chart.element, { clientX: layout.cx, clientY: layout.cy })
            fireEvent.click(chart.element)
            expect(onSliceClick).not.toHaveBeenCalled()
        })
    })

    describe('error boundary', () => {
        it('reports render errors through onError', async () => {
            const onError = jest.fn()
            const tooltip = (): React.ReactNode => {
                throw new Error('boom')
            }
            const consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {})
            try {
                const { chart } = renderHogChart(
                    <PieChart series={SERIES} theme={THEME} tooltip={tooltip} onError={onError} />
                )
                const layout = layoutFor(SERIES)
                fireEvent.mouseMove(chart.element, pointInSlice(layout, 0))
                await waitFor(() => expect(onError).toHaveBeenCalled())
            } finally {
                consoleErrorSpy.mockRestore()
            }
        })
    })
})
