import { createElement } from 'react'
import { renderToString } from 'react-dom/server'

import * as charts from '../dist/index.js'

const labels = ['Mon', 'Tue']
const dates = ['2026-01-05', '2026-01-06']
const series = [{ key: 'a', label: 'A', data: [1, 2] }]
const parts = [{ key: 'a', label: 'A', data: [1] }]
const box = { min: 0, p25: 1, median: 2, mean: 2, p75: 3, max: 4 }

const cases = {
    LineChart: { series, labels },
    TimeSeriesLineChart: { series, labels: dates },
    BarChart: { series, labels },
    TimeSeriesBarChart: { series, labels: dates },
    ComboChart: { series, labels },
    TimeSeriesComboChart: { series, labels: dates },
    FunnelChart: { series, steps: labels },
    SlopeChart: { series, labels },
    BoxPlot: { series: [{ key: 'a', label: 'A', data: [box, box] }], labels },
    ScatterChart: { series: [{ key: 'a', label: 'A', points: [{ x: 1, y: 2 }] }] },
    Heatmap: {
        xLabels: labels,
        yLabels: labels,
        cells: [
            [1, 2],
            [3, 4],
        ],
    },
    PieChart: { series: parts },
    ProportionBar: { series: parts },
    BarList: { series: parts },
    StackedBarList: { series, labels, renderLabel: () => null, renderValue: () => null },
    Sparkline: { data: [1, 2] },
    Gauge: { value: 50 },
    SankeyChart: {
        nodes: [
            { id: 'a', label: 'A' },
            { id: 'b', label: 'B' },
        ],
        links: [{ source: 'a', target: 'b', value: 1 }],
    },
    FlameGraph: { data: { name: 'root', value: 2, children: [{ name: 'leaf', value: 1 }] } },
    Legend: { items: [{ key: 'a', label: 'A', color: '#1d4aff' }] },
}

const failures = []
for (const [name, props] of Object.entries(cases)) {
    try {
        renderToString(createElement(charts[name], props))
    } catch (error) {
        failures.push(`${name}: ${error.message}`)
    }
}

if (failures.length > 0) {
    console.error(`Server render failed for ${failures.length} of ${Object.keys(cases).length} charts:`)
    failures.forEach((failure) => console.error(`  ${failure}`))
    process.exit(1)
}
