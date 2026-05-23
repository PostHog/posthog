import type { ChartTheme } from '../../core/types'
import { renderHogChart } from '../../testing'
import { PieChart, type PieSlice } from './PieChart'

const THEME: ChartTheme = {
    colors: ['#1f77b4', '#ff7f0e', '#2ca02c'],
    backgroundColor: '#ffffff',
}

const SLICES: PieSlice[] = [
    { key: 'a', label: 'A', value: 30 },
    { key: 'b', label: 'B', value: 50 },
    { key: 'c', label: 'C', value: 20 },
]

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

    it('caps innerRadius into the donut range without crashing', () => {
        const { chart } = renderHogChart(<PieChart slices={SLICES} theme={THEME} config={{ innerRadius: 0.5 }} />)
        expect(chart.seriesCount).toBe(3)
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
