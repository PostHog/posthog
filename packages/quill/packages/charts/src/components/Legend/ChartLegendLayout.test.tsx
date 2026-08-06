import { render } from '@testing-library/react'

import { ChartLegendLayout } from './ChartLegendLayout'

const LEGEND = <div data-attr="legend">L</div>
const CHART = <div data-attr="chart">C</div>

function root(props: Parameters<typeof ChartLegendLayout>[0]): HTMLElement {
    return render(<ChartLegendLayout {...props} />).container.firstChild as HTMLElement
}

describe('ChartLegendLayout', () => {
    it.each([
        ['top', 'flex-col', 0],
        ['bottom', 'flex-col', 1],
        ['left', 'flex-row', 0],
        ['right', 'flex-row', 1],
    ] as const)('position=%s uses %s with legend at child index %s', (position, flex, legendIndex) => {
        const r = root({ legend: LEGEND, position, children: CHART })
        expect(r.className).toContain(flex)
        expect(r.children[legendIndex].querySelector('[data-attr="legend"]')).not.toBeNull()
        expect(r.children[1 - legendIndex].querySelector('[data-attr="chart"]')).not.toBeNull()
    })

    it('passes gap through as an inline style (default 8px)', () => {
        expect(root({ legend: LEGEND, children: CHART }).style.gap).toBe('8px')
        expect(root({ legend: LEGEND, gap: 24, children: CHART }).style.gap).toBe('24px')
    })

    it.each([null, undefined, false] as const)('omits the legend slot when legend is %p', (legend) => {
        const r = root({ legend, children: CHART })
        expect(r.children).toHaveLength(1)
        expect(r.querySelector('[data-attr="chart"]')).not.toBeNull()
    })
})
