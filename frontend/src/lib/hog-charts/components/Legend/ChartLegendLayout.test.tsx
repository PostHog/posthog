import { render } from '@testing-library/react'

import { ChartLegendLayout } from './ChartLegendLayout'

function setup(props: Parameters<typeof ChartLegendLayout>[0]): {
    root: HTMLElement
    legend: HTMLElement | null
    chart: HTMLElement
} {
    const { container } = render(<ChartLegendLayout {...props} />)
    const root = container.firstChild as HTMLElement
    const legend = root.querySelector<HTMLElement>('[data-attr="hog-charts-legend-slot"]')
    const chart = root.querySelector<HTMLElement>('[data-attr="hog-charts-chart-slot"]')!
    return { root, legend, chart }
}

const LEGEND = <div data-attr="my-legend">legend</div>
const CHART = <div data-attr="my-chart">chart</div>

describe('ChartLegendLayout', () => {
    it("default position 'top' puts the legend before the chart in column flex", () => {
        const { root, legend, chart } = setup({ legend: LEGEND, children: CHART })
        expect(root.className).toContain('flex-col')
        expect(legend).not.toBeNull()
        expect(root.children[0]).toBe(legend)
        expect(root.children[1]).toBe(chart)
    })

    it("position 'bottom' puts the legend after the chart in column flex", () => {
        const { root, legend, chart } = setup({ legend: LEGEND, position: 'bottom', children: CHART })
        expect(root.className).toContain('flex-col')
        expect(root.children[0]).toBe(chart)
        expect(root.children[1]).toBe(legend)
    })

    it("position 'left' puts the legend before the chart in row flex", () => {
        const { root, legend, chart } = setup({ legend: LEGEND, position: 'left', children: CHART })
        expect(root.className).toContain('flex-row')
        expect(root.children[0]).toBe(legend)
        expect(root.children[1]).toBe(chart)
    })

    it("position 'right' puts the legend after the chart in row flex", () => {
        const { root, legend, chart } = setup({ legend: LEGEND, position: 'right', children: CHART })
        expect(root.className).toContain('flex-row')
        expect(root.children[0]).toBe(chart)
        expect(root.children[1]).toBe(legend)
    })

    it.each([
        ['start', 'items-start'],
        ['center', 'items-center'],
        ['end', 'items-end'],
    ] as const)('align=%s applies %s', (align, expected) => {
        const { root } = setup({ legend: LEGEND, align, children: CHART })
        expect(root.className).toContain(expected)
    })

    it('passes the gap prop through as an inline gap style value', () => {
        const { root } = setup({ legend: LEGEND, gap: 24, children: CHART })
        expect(root.style.gap).toBe('24px')
    })

    it('defaults gap to 8 pixels when not provided', () => {
        const { root } = setup({ legend: LEGEND, children: CHART })
        expect(root.style.gap).toBe('8px')
    })

    it('omits the legend slot but still renders children when legend is null', () => {
        const { root, legend, chart } = setup({ legend: null, children: CHART })
        expect(legend).toBeNull()
        expect(root.children).toHaveLength(1)
        expect(root.children[0]).toBe(chart)
    })

    it('omits the legend slot when legend is undefined', () => {
        const { legend, chart } = setup({ legend: undefined, children: CHART })
        expect(legend).toBeNull()
        expect(chart.textContent).toBe('chart')
    })

    it('omits the legend slot when legend is false', () => {
        const { legend, chart } = setup({ legend: false, children: CHART })
        expect(legend).toBeNull()
        expect(chart.textContent).toBe('chart')
    })

    it.each(['top', 'bottom', 'left', 'right'] as const)('children render unchanged at position=%s', (position) => {
        const { chart } = setup({ legend: LEGEND, position, children: CHART })
        expect(chart.textContent).toBe('chart')
    })
})
