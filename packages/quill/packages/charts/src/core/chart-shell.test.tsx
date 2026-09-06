import type { ChartTheme, Series } from './types'
import { LineChart } from '../charts/LineChart/LineChart'
import { renderHogChart } from '../testing'

const THEME: ChartTheme = {
    colors: ['#1f77b4'],
    backgroundColor: '#ffffff',
    gridColor: '#eeeeee',
    crosshairColor: '#888888',
}

const LABELS = ['Mon', 'Tue', 'Wed']
const SERIES: Series[] = [{ key: 'visits', label: 'Visits', color: '', data: [20, 35, 28] }]

describe('chart shell', () => {
    // jsdom applies no stylesheet, which is the state a page is in before the app stylesheet
    // lands. Moving this containment back into utility classes reopens the growth loop.
    it('contains the chart with no stylesheet applied', () => {
        const { chart } = renderHogChart(<LineChart series={SERIES} labels={LABELS} theme={THEME} />)

        expect(getComputedStyle(chart.element).position).toBe('relative')
        expect(getComputedStyle(chart.element).overflow).toBe('hidden')
        for (const layer of chart.element.children) {
            expect(getComputedStyle(layer).position).toBe('absolute')
        }
    })
})
