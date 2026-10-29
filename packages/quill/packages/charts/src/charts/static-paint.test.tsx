import { fireEvent } from '@testing-library/react'
import React from 'react'

import { MetricCard } from '../components/MetricCard/MetricCard'
import type { ChartTheme, Series } from '../core/types'
import { renderChart } from '../testing'
import { BarChart } from './BarChart/BarChart'
import { BarList } from './BarList/BarList'
import { StackedBarList } from './BarList/StackedBarList'
import { BoxPlot } from './BoxPlot/BoxPlot'
import type { BoxPlotSeries } from './BoxPlot/types'
import { ComboChart } from './ComboChart/ComboChart'
import { FunnelChart } from './FunnelChart/FunnelChart'
import { Heatmap } from './Heatmap/Heatmap'
import { LineChart } from './LineChart/LineChart'
import { PieChart } from './PieChart/PieChart'
import { ProportionBar } from './ProportionBar/ProportionBar'
import { SankeyChart } from './SankeyChart/SankeyChart'
import type { SankeyLinkInput, SankeyNodeInput } from './SankeyChart/sankey-data'
import { ScatterChart } from './ScatterChart/ScatterChart'
import type { ScatterSeries } from './ScatterChart/types'
import { SlopeChart } from './SlopeChart/SlopeChart'
import { Sparkline } from './Sparkline/Sparkline'
import { TimeSeriesBarChart } from './TimeSeriesBarChart/TimeSeriesBarChart'
import { TimeSeriesComboChart } from './TimeSeriesComboChart/TimeSeriesComboChart'
import { TimeSeriesLineChart } from './TimeSeriesLineChart/TimeSeriesLineChart'

const THEME: ChartTheme = { colors: ['#1f77b4', '#ff7f0e', '#2ca02c'], backgroundColor: '#ffffff' }
const LABELS = ['2024-01-01', '2024-01-02', '2024-01-03']
const SERIES: Series[] = [
    { key: 'a', label: 'A', data: [10, 30, 20] },
    { key: 'b', label: 'B', data: [5, 15, 25] },
]
const COMBO_SERIES: Series[] = [
    { key: 'bars', label: 'Bars', data: [10, 30, 20], type: 'bar' },
    { key: 'line', label: 'Line', data: [15, 25, 20], type: 'line' },
]
const SLOPE_LABELS = ['Before', 'After']
const DATA = [100, 200, 300]
const BOX_SERIES: BoxPlotSeries[] = [
    {
        key: 'a',
        label: 'A',
        data: LABELS.map(() => ({ min: 0, p25: 25, median: 50, mean: 55, p75: 75, max: 100 })),
    },
]
const SCATTER_SERIES: ScatterSeries[] = [
    {
        key: 'a',
        label: 'A',
        points: [
            { x: 0, y: 0 },
            { x: 50, y: 50 },
            { x: 100, y: 100 },
        ],
    },
]
const CELLS = [
    [3, 0, 1],
    [10, 4, 0],
    [0, 1, 6],
]
const NODES: SankeyNodeInput[] = [
    { id: 'start', label: 'Start' },
    { id: 'done', label: 'Done' },
]
const LINKS: SankeyLinkInput[] = [{ source: 'start', target: 'done', value: 12 }]
const renderRowLabel = (i: number): string => `Row ${i}`

// Each call builds fresh inline literals, like a consumer that does not memoize `config`.
const CHARTS: [string, () => React.ReactElement][] = [
    ['LineChart', () => <LineChart series={SERIES} labels={LABELS} theme={THEME} config={{ showGrid: true }} />],
    ['BarChart', () => <BarChart series={SERIES} labels={LABELS} theme={THEME} config={{ showGrid: true }} />],
    [
        'ComboChart',
        () => <ComboChart series={COMBO_SERIES} labels={LABELS} theme={THEME} config={{ showGrid: true }} />,
    ],
    [
        'TimeSeriesLineChart',
        () => <TimeSeriesLineChart series={SERIES} labels={LABELS} theme={THEME} config={{ showGrid: true }} />,
    ],
    [
        'TimeSeriesBarChart',
        () => <TimeSeriesBarChart series={SERIES} labels={LABELS} theme={THEME} config={{ showGrid: true }} />,
    ],
    [
        'TimeSeriesComboChart',
        () => <TimeSeriesComboChart series={COMBO_SERIES} labels={LABELS} theme={THEME} config={{ showGrid: true }} />,
    ],
    ['FunnelChart', () => <FunnelChart steps={LABELS} series={SERIES} theme={THEME} config={{ showGrid: true }} />],
    ['ScatterChart', () => <ScatterChart series={SCATTER_SERIES} theme={THEME} config={{ showGrid: true }} />],
    ['BoxPlot', () => <BoxPlot series={BOX_SERIES} labels={LABELS} theme={THEME} config={{ showGrid: true }} />],
    ['Heatmap', () => <Heatmap xLabels={LABELS} yLabels={LABELS} cells={CELLS} theme={THEME} config={{}} />],
    ['SlopeChart', () => <SlopeChart series={SERIES} labels={SLOPE_LABELS} theme={THEME} config={{}} />],
    ['PieChart', () => <PieChart series={SERIES} theme={THEME} config={{}} />],
    ['ProportionBar', () => <ProportionBar series={SERIES} theme={THEME} config={{}} />],
    ['BarList', () => <BarList series={SERIES} theme={THEME} config={{ valueDisplay: 'both' }} />],
    [
        'StackedBarList',
        () => (
            <StackedBarList
                labels={LABELS}
                series={SERIES}
                theme={THEME}
                config={{}}
                renderLabel={renderRowLabel}
                renderValue={renderRowLabel}
            />
        ),
    ],
    ['SankeyChart', () => <SankeyChart nodes={NODES} links={LINKS} theme={THEME} config={{ showNodeValues: true }} />],
    ['Sparkline', () => <Sparkline data={DATA} labels={LABELS} theme={THEME} />],
    [
        'MetricCard',
        () => <MetricCard title="Total" data={DATA} labels={LABELS} theme={THEME} formatValue={(v) => `$${v}`} />,
    ],
]

const PAINT_ATTRIBUTE = 'data-hog-charts-paint'

/** Counts the static repaints a canvas schedules from now on. Each one writes `pending` first. */
function countStaticPaints(canvas: HTMLCanvasElement): () => number {
    const observer = new MutationObserver(() => {})
    observer.observe(canvas, { attributeFilter: [PAINT_ATTRIBUTE], attributeOldValue: true })
    const records: MutationRecord[] = []
    return () => {
        records.push(...observer.takeRecords())
        // A record holds the value it replaced, so the value it wrote is the next record's old value.
        const written = [...records.slice(1).map((r) => r.oldValue), canvas.getAttribute(PAINT_ATTRIBUTE)]
        return records.length === 0 ? 0 : written.filter((value) => value === 'pending').length
    }
}

describe('static canvas paints', () => {
    it.each(CHARTS)('%s does not repaint on a same-props rerender or on hover', (_, renderUi) => {
        const { chart, rerender } = renderChart(renderUi())
        const paints = countStaticPaints(chart.canvas)

        rerender(renderUi())
        for (const clientX of [100, 400, 700]) {
            fireEvent.mouseMove(chart.element, { clientX, clientY: 200 })
        }
        fireEvent.mouseLeave(chart.element)

        expect(paints()).toBe(0)
    })

    it('counts the repaint a new series causes', () => {
        const { chart, rerender } = renderChart(<LineChart series={SERIES} labels={LABELS} theme={THEME} />)
        const paints = countStaticPaints(chart.canvas)

        rerender(<LineChart series={[...SERIES]} labels={LABELS} theme={THEME} />)

        expect(paints()).toBe(1)
    })
})
