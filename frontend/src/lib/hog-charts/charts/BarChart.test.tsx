import { cleanup, render } from '@testing-library/react'

import type { ChartTheme, Series } from '../core/types'
import { setupJsdom } from '../test-helpers'
import { BarChart } from './BarChart'

const THEME: ChartTheme = {
    colors: ['#1f77b4', '#ff7f0e', '#2ca02c'],
    backgroundColor: '#ffffff',
    gridColor: '#eeeeee',
    crosshairColor: '#888888',
}

const SERIES: Series[] = [
    { key: 'a', label: 'A', data: [10, 20, 30] },
    { key: 'b', label: 'B', data: [5, 15, 25] },
]

const LABELS = ['Mon', 'Tue', 'Wed']

type Layout = 'stacked' | 'grouped' | 'percent'
type Orientation = 'vertical' | 'horizontal'

describe('BarChart', () => {
    let teardown: () => void

    beforeEach(() => {
        teardown = setupJsdom()
    })

    afterEach(() => {
        teardown()
        cleanup()
    })

    describe.each<[Layout, Orientation]>([
        ['stacked', 'vertical'],
        ['grouped', 'vertical'],
        ['percent', 'vertical'],
        ['stacked', 'horizontal'],
        ['grouped', 'horizontal'],
        ['percent', 'horizontal'],
    ])('%s / %s', (barLayout, axisOrientation) => {
        it('renders a canvas without throwing', () => {
            const { container } = render(
                <BarChart series={SERIES} labels={LABELS} theme={THEME} config={{ barLayout, axisOrientation }} />
            )
            expect(container.querySelector('canvas')).not.toBeNull()
        })
    })

    it('forwards `dataAttr` to the chart wrapper for product-test selection', () => {
        const { container } = render(
            <BarChart series={SERIES} labels={LABELS} theme={THEME} dataAttr="bar-chart-instance" />
        )
        expect(container.querySelector('[data-attr="bar-chart-instance"]')).not.toBeNull()
    })

    it('renders empty state without crashing', () => {
        const { container } = render(<BarChart series={[]} labels={[]} theme={THEME} />)
        expect(container.querySelector('canvas')).not.toBeNull()
    })

    it('skips excluded series in stacked layout', () => {
        const series: Series[] = [
            { key: 'a', label: 'A', data: [10, 20, 30] },
            { key: 'b', label: 'B', data: [5, 15, 25], visibility: { excluded: true } },
            { key: 'c', label: 'C', data: [3, 6, 9] },
        ]
        const { container } = render(
            <BarChart series={series} labels={LABELS} theme={THEME} config={{ barLayout: 'stacked' }} />
        )
        expect(container.querySelector('canvas')).not.toBeNull()
    })

    it('renders custom percent formatter when consumer supplies one', () => {
        const formatter = jest.fn((v: number) => `${Math.round(v * 1000) / 10}‰`)
        render(
            <BarChart
                series={SERIES}
                labels={LABELS}
                theme={THEME}
                config={{ barLayout: 'percent', yTickFormatter: formatter }}
            />
        )
        expect(formatter).toHaveBeenCalled()
        // Built-in default would have produced '%' suffix; consumer's '‰' wins.
        expect(formatter.mock.results.some((r) => typeof r.value === 'string' && r.value.endsWith('‰'))).toBe(true)
    })

    it('applies a default percent formatter when consumer omits one', () => {
        const { container } = render(
            <BarChart series={SERIES} labels={LABELS} theme={THEME} config={{ barLayout: 'percent' }} />
        )
        // AxisLabels renders tick text into divs; default percent formatter emits values like "50%".
        const text = container.textContent ?? ''
        expect(text).toMatch(/\d+%/)
    })

    it('tolerates NaN data values without throwing', () => {
        const broken: Series[] = [{ key: 'a', label: 'A', data: [Number.NaN, Number.NaN, Number.NaN] }]
        const { container } = render(<BarChart series={broken} labels={LABELS} theme={THEME} />)
        expect(container.querySelector('canvas')).not.toBeNull()
    })
})
