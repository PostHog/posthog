import { cleanup, render } from '@testing-library/react'

import type { ChartTheme, Series } from '../core/types'
import { renderHogChart, setupJsdom, setupSyncRaf } from '../testing'
import { LineChart } from './LineChart'

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

describe('LineChart', () => {
    let teardownJsdom: () => void
    let teardownRaf: () => void

    beforeEach(() => {
        teardownJsdom = setupJsdom()
        teardownRaf = setupSyncRaf()
    })

    afterEach(() => {
        teardownRaf()
        teardownJsdom()
        cleanup()
    })

    it.each([
        ['default config', SERIES, undefined],
        ['area mode', [{ key: 'a', label: 'A', data: [10, 20, 30], fill: {} }] as Series[], undefined],
        ['percent stack mode', SERIES, { percentStackView: true }],
    ] as const)('renders without throwing in %s', (_, series, config) => {
        const { chart } = renderHogChart(<LineChart series={series} labels={LABELS} theme={THEME} config={config} />)
        expect(chart.seriesCount).toBeGreaterThan(0)
    })

    it('renders empty state without crashing', () => {
        const { chart } = renderHogChart(<LineChart series={[]} labels={[]} theme={THEME} />)
        expect(chart.seriesCount).toBe(0)
    })

    it('skips excluded series', () => {
        const series: Series[] = [
            { key: 'a', label: 'A', data: [10, 20, 30] },
            { key: 'b', label: 'B', data: [5, 15, 25], visibility: { excluded: true } },
            { key: 'c', label: 'C', data: [3, 6, 9] },
        ]
        const { chart } = renderHogChart(<LineChart series={series} labels={LABELS} theme={THEME} />)
        expect(chart.seriesCount).toBe(2)
    })

    it('forwards `dataAttr` to the chart wrapper for product-test selection', () => {
        const { container } = render(
            <LineChart series={SERIES} labels={LABELS} theme={THEME} dataAttr="line-chart-instance" />
        )
        expect(container.querySelector('[data-attr="line-chart-instance"]')).not.toBeNull()
    })

    it('applies a default percent formatter when consumer omits one in percent stack mode', () => {
        const { chart } = renderHogChart(
            <LineChart series={SERIES} labels={LABELS} theme={THEME} config={{ percentStackView: true }} />
        )
        expect(chart.yTicks().some((t) => /\d+%/.test(t))).toBe(true)
    })

    it('uses custom yTickFormatter when supplied in percent stack mode', () => {
        const formatter = jest.fn((v: number) => `${Math.round(v * 1000) / 10}‰`)
        const { chart } = renderHogChart(
            <LineChart
                series={SERIES}
                labels={LABELS}
                theme={THEME}
                config={{ percentStackView: true, yTickFormatter: formatter }}
            />
        )
        expect(formatter).toHaveBeenCalled()
        expect(chart.yTicks().some((t) => t.endsWith('‰'))).toBe(true)
    })

    it('tolerates NaN data values without throwing', () => {
        const broken: Series[] = [{ key: 'a', label: 'A', data: [Number.NaN, Number.NaN, Number.NaN] }]
        const { container } = render(<LineChart series={broken} labels={LABELS} theme={THEME} />)
        expect(container.querySelector('canvas')).not.toBeNull()
    })
})
