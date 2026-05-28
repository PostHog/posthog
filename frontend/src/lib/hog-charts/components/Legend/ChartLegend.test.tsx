import { render } from '@testing-library/react'

import { ChartLegend } from './ChartLegend'
import type { LegendItem } from './Legend'

const ITEMS: LegendItem[] = [
    { key: 'a', label: 'A', color: '#000' },
    { key: 'b', label: 'B', color: '#fff' },
]

describe('ChartLegend', () => {
    it('renders children unwrapped when show is false', () => {
        const { container } = render(
            <ChartLegend show={false} items={ITEMS}>
                <div data-attr="chart">C</div>
            </ChartLegend>
        )
        expect(container.children).toHaveLength(1)
        expect((container.firstChild as HTMLElement).getAttribute('data-attr')).toBe('chart')
        expect(container.textContent).not.toContain('A')
    })

    it('renders children unwrapped when items is empty', () => {
        const { container } = render(
            <ChartLegend items={[]}>
                <div data-attr="chart">C</div>
            </ChartLegend>
        )
        expect(container.children).toHaveLength(1)
        expect((container.firstChild as HTMLElement).getAttribute('data-attr')).toBe('chart')
    })

    it('renders legend and chart inside a flex wrapper when show is true', () => {
        const { container } = render(
            <ChartLegend show items={ITEMS} legendDataAttr="my-legend">
                <div data-attr="chart">C</div>
            </ChartLegend>
        )
        expect(container.textContent).toContain('A')
        expect(container.textContent).toContain('B')
        expect(container.querySelector('[data-attr="chart"]')).not.toBeNull()
        expect(container.querySelector('[data-attr="my-legend"]')).not.toBeNull()
        const outer = container.firstChild as HTMLElement
        expect(outer.className).toContain('flex-1')
        expect(outer.className).toContain('min-h-0')
    })

    it.each([
        ['top', 'flex-col'],
        ['bottom', 'flex-col'],
        ['left', 'flex-row'],
        ['right', 'flex-row'],
    ] as const)('position=%s sets layout direction to %s', (position, direction) => {
        const { container } = render(
            <ChartLegend items={ITEMS} position={position}>
                <div>C</div>
            </ChartLegend>
        )
        expect((container.firstChild as HTMLElement).className).toContain(direction)
    })
})
