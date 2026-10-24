import { render } from '@testing-library/react'
import React from 'react'

import { BarChart } from '../charts/BarChart/BarChart'
import { BarList } from '../charts/BarList/BarList'
import { StackedBarList } from '../charts/BarList/StackedBarList'
import { BoxPlot } from '../charts/BoxPlot/BoxPlot'
import { ComboChart } from '../charts/ComboChart/ComboChart'
import { FunnelChart } from '../charts/FunnelChart/FunnelChart'
import { Heatmap } from '../charts/Heatmap/Heatmap'
import { LineChart } from '../charts/LineChart/LineChart'
import { ProportionBar } from '../charts/ProportionBar/ProportionBar'
import { ScatterChart } from '../charts/ScatterChart/ScatterChart'
import { SlopeChart } from '../charts/SlopeChart/SlopeChart'
import { Sparkline } from '../charts/Sparkline/Sparkline'
import { TimeSeriesBarChart } from '../charts/TimeSeriesBarChart/TimeSeriesBarChart'
import { TimeSeriesComboChart } from '../charts/TimeSeriesComboChart/TimeSeriesComboChart'
import { TimeSeriesLineChart } from '../charts/TimeSeriesLineChart/TimeSeriesLineChart'
import { MetricCard } from '../components/MetricCard/MetricCard'
import { ensureJsdom } from '../testing/jsdom'
import type { ChartTheme, Series } from './types'

type OnError = (error: Error, info: React.ErrorInfo) => void

// The base `Chart` reads `axisColor` while rendering and no wrapper chart does, so the error is
// raised inside the innermost chart's own boundary.
const THROWING_THEME = {
    colors: ['#1f77b4', '#ff7f0e'],
    backgroundColor: '#ffffff',
    get axisColor(): string {
        throw new Error('boom')
    },
} as ChartTheme

const LABELS = ['2024-01-01', '2024-01-02', '2024-01-03']
const SERIES: Series[] = [
    { key: 'a', label: 'A', data: [1, 2, 3] },
    { key: 'b', label: 'B', data: [3, 2, 1] },
]
const PARTS: Series[] = [
    { key: 'a', label: 'A', data: [6] },
    { key: 'b', label: 'B', data: [4] },
]
const BOX = { min: 0, p25: 25, median: 50, mean: 55, p75: 75, max: 100 }

const CHARTS: [string, (onError: OnError) => React.ReactElement][] = [
    ['LineChart', (onError) => <LineChart series={SERIES} labels={LABELS} theme={THROWING_THEME} onError={onError} />],
    ['BarChart', (onError) => <BarChart series={SERIES} labels={LABELS} theme={THROWING_THEME} onError={onError} />],
    [
        'ComboChart',
        (onError) => <ComboChart series={SERIES} labels={LABELS} theme={THROWING_THEME} onError={onError} />,
    ],
    [
        'TimeSeriesLineChart',
        (onError) => <TimeSeriesLineChart series={SERIES} labels={LABELS} theme={THROWING_THEME} onError={onError} />,
    ],
    [
        'TimeSeriesBarChart',
        (onError) => <TimeSeriesBarChart series={SERIES} labels={LABELS} theme={THROWING_THEME} onError={onError} />,
    ],
    [
        'TimeSeriesComboChart',
        (onError) => <TimeSeriesComboChart series={SERIES} labels={LABELS} theme={THROWING_THEME} onError={onError} />,
    ],
    [
        'BoxPlot',
        (onError) => (
            <BoxPlot
                series={[{ key: 'a', label: 'A', data: [BOX, BOX, BOX] }]}
                labels={LABELS}
                theme={THROWING_THEME}
                onError={onError}
            />
        ),
    ],
    [
        'SlopeChart',
        (onError) => (
            <SlopeChart
                series={[{ key: 'a', label: 'A', data: [1, 2] }]}
                labels={['Before', 'After']}
                theme={THROWING_THEME}
                onError={onError}
            />
        ),
    ],
    ['Sparkline', (onError) => <Sparkline data={[1, 2, 3]} labels={LABELS} theme={THROWING_THEME} onError={onError} />],
    [
        'MetricCard',
        (onError) => (
            <MetricCard title="Visits" data={[1, 2, 3]} labels={LABELS} theme={THROWING_THEME} onError={onError} />
        ),
    ],
    ['BarList', (onError) => <BarList series={PARTS} theme={THROWING_THEME} onError={onError} />],
    [
        'StackedBarList',
        (onError) => (
            <StackedBarList
                labels={['Row 1', 'Row 2', 'Row 3']}
                series={SERIES}
                theme={THROWING_THEME}
                renderLabel={(i) => `Row ${i}`}
                renderValue={(i) => i}
                onError={onError}
            />
        ),
    ],
    ['ProportionBar', (onError) => <ProportionBar series={PARTS} theme={THROWING_THEME} onError={onError} />],
    [
        'FunnelChart',
        (onError) => (
            <FunnelChart
                steps={['Pageview', 'Signup']}
                series={[{ key: 'all', label: 'All', data: [100, 40] }]}
                theme={THROWING_THEME}
                onError={onError}
            />
        ),
    ],
    [
        'Heatmap',
        (onError) => (
            <Heatmap
                xLabels={['10:00', '10:02']}
                yLabels={['1ms', '2ms']}
                cells={[
                    [1, 2],
                    [3, 4],
                ]}
                theme={THROWING_THEME}
                onError={onError}
            />
        ),
    ],
    [
        'ScatterChart',
        (onError) => (
            <ScatterChart
                series={[{ key: 'a', label: 'A', points: [{ x: 1, y: 2 }] }]}
                theme={THROWING_THEME}
                onError={onError}
            />
        ),
    ],
]

describe('ChartErrorBoundary', () => {
    beforeAll(() => ensureJsdom())

    it.each(CHARTS)('%s reports an error from its inner chart through onError', (_name, renderChart) => {
        const onError = jest.fn()
        const consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {})
        try {
            const { container } = render(renderChart(onError))
            expect(onError).toHaveBeenCalledWith(expect.objectContaining({ message: 'boom' }), expect.anything())
            expect(container.textContent).toContain('Something went wrong')
        } finally {
            consoleErrorSpy.mockRestore()
        }
    })
})
