import { render } from '@testing-library/react'
import React from 'react'

import { BarChart } from '../charts/BarChart/BarChart'
import { BarList } from '../charts/BarList/BarList'
import { StackedBarList } from '../charts/BarList/StackedBarList'
import { BoxPlot } from '../charts/BoxPlot/BoxPlot'
import { ComboChart } from '../charts/ComboChart/ComboChart'
import { Gauge } from '../charts/Gauge/Gauge'
import { Heatmap } from '../charts/Heatmap/Heatmap'
import { LineChart } from '../charts/LineChart/LineChart'
import { PieChart } from '../charts/PieChart/PieChart'
import { ProportionBar } from '../charts/ProportionBar/ProportionBar'
import { ScatterChart } from '../charts/ScatterChart/ScatterChart'
import { SlopeChart } from '../charts/SlopeChart/SlopeChart'
import { Sparkline } from '../charts/Sparkline/Sparkline'
import { MetricCard } from '../components/MetricCard/MetricCard'
import { setupChartTests } from '../testing'
import type { ChartTheme, Series } from './types'

let mockShellThrows = false

jest.mock('./chart-shell', () => {
    const actual = jest.requireActual('./chart-shell')
    const { createElement } = jest.requireActual('react')
    return {
        ...actual,
        ChartShell: (props: Record<string, unknown>): unknown => {
            if (mockShellThrows) {
                throw new Error('boom')
            }
            return createElement(actual.ChartShell, props)
        },
    }
})

const THEME: ChartTheme = { colors: ['#1f77b4', '#ff7f0e'], backgroundColor: '#ffffff' }
const LABELS = ['Mon', 'Tue']
const BOX = { min: 0, p25: 25, median: 50, mean: 55, p75: 75, max: 100 }

const series = (n: number): Series[] => [{ key: 'a', label: 'A', data: [n, n + 1] }]
const parts = (n: number): Series[] => [{ key: 'a', label: 'A', data: [n] }]

describe('ChartErrorBoundary', () => {
    setupChartTests()

    let consoleError: jest.SpyInstance

    beforeEach(() => {
        consoleError = jest.spyOn(console, 'error').mockImplementation(() => {})
    })

    afterEach(() => {
        mockShellThrows = false
        consoleError.mockRestore()
    })

    it.each<[string, (n: number) => React.ReactElement]>([
        ['LineChart', (n) => <LineChart series={series(n)} labels={LABELS} theme={THEME} />],
        ['BarChart', (n) => <BarChart series={series(n)} labels={LABELS} theme={THEME} />],
        ['ComboChart', (n) => <ComboChart series={series(n)} labels={LABELS} theme={THEME} />],
        ['SlopeChart', (n) => <SlopeChart series={series(n)} labels={LABELS} theme={THEME} />],
        [
            'BoxPlot',
            (n) => (
                <BoxPlot
                    series={[{ key: 'a', label: 'A', data: [BOX, { ...BOX, max: 100 + n }] }]}
                    labels={LABELS}
                    theme={THEME}
                />
            ),
        ],
        [
            'ScatterChart',
            (n) => <ScatterChart series={[{ key: 'a', label: 'A', points: [{ x: n, y: n }] }]} theme={THEME} />,
        ],
        [
            'Heatmap',
            (n) => (
                <Heatmap
                    xLabels={LABELS}
                    yLabels={LABELS}
                    cells={[
                        [n, 1],
                        [1, n],
                    ]}
                    theme={THEME}
                />
            ),
        ],
        ['PieChart', (n) => <PieChart series={parts(n)} theme={THEME} />],
        ['ProportionBar', (n) => <ProportionBar series={parts(n)} theme={THEME} />],
        ['BarList', (n) => <BarList series={parts(n)} theme={THEME} />],
        [
            'StackedBarList',
            (n) => (
                <StackedBarList
                    series={series(n)}
                    labels={LABELS}
                    theme={THEME}
                    renderLabel={() => null}
                    renderValue={() => null}
                />
            ),
        ],
        ['Sparkline', (n) => <Sparkline data={[n, n + 1]} labels={LABELS} theme={THEME} />],
        ['Gauge', (n) => <Gauge value={n} theme={THEME} />],
        ['MetricCard', (n) => <MetricCard title="Total" data={[n, n + 1]} labels={LABELS} theme={THEME} />],
    ])('%s recovers from a render error when its data changes', (_, chart) => {
        mockShellThrows = true
        const { container, rerender } = render(chart(1))
        expect(container.textContent).toContain('Something went wrong')

        mockShellThrows = false
        rerender(chart(2))
        expect(container.textContent).not.toContain('Something went wrong')
    })

    it('keeps the fallback when a NaN value does not change', () => {
        mockShellThrows = true
        const { container, rerender } = render(<Gauge value={NaN} theme={THEME} />)

        rerender(<Gauge value={NaN} theme={THEME} />)
        expect(container.textContent).toContain('Something went wrong')
    })
})
