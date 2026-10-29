// Measures React-side cost per hover and per same-props parent re-render for every chart. It also counts
// writes of the static canvas's `data-hog-charts-paint` attribute (two per repaint) and layout-context
// changes. jsdom mocks the canvas, so draw time is not measured. Jest only collects `*.test.*`, so CI never
// runs this file. Run it on two checkouts and compare:
//
//   cd frontend && pnpm exec jest --testMatch '**/*.bench.tsx' ../packages/quill/packages/charts/src/charts/render-cost.bench.tsx
//
// Set BENCH_OUT=<path> to also write the results as JSON.
import { act, fireEvent } from '@testing-library/react'
import { writeFileSync } from 'fs'
import React from 'react'

import { MetricCard } from '../components/MetricCard/MetricCard'
import { useChartLayout } from '../core/chart-context'
import type { ChartTheme, Series } from '../core/types'
import { renderChart } from '../testing'
import { BarChart } from './BarChart/BarChart'
import { BarList } from './BarList/BarList'
import { StackedBarList } from './BarList/StackedBarList'
import { BoxPlot } from './BoxPlot/BoxPlot'
import { ComboChart } from './ComboChart/ComboChart'
import { FunnelChart } from './FunnelChart/FunnelChart'
import { Heatmap } from './Heatmap/Heatmap'
import { LineChart } from './LineChart/LineChart'
import { PieChart } from './PieChart/PieChart'
import { ProportionBar } from './ProportionBar/ProportionBar'
import { SankeyChart } from './SankeyChart/SankeyChart'
import { ScatterChart } from './ScatterChart/ScatterChart'
import { SlopeChart } from './SlopeChart/SlopeChart'
import { Sparkline } from './Sparkline/Sparkline'
import { TimeSeriesBarChart } from './TimeSeriesBarChart/TimeSeriesBarChart'
import { TimeSeriesComboChart } from './TimeSeriesComboChart/TimeSeriesComboChart'
import { TimeSeriesLineChart } from './TimeSeriesLineChart/TimeSeriesLineChart'

const ROUNDS = 5
const HOVERS_PER_ROUND = 60
const RERENDERS_PER_ROUND = 10

const THEME: ChartTheme = { colors: ['#1f77b4', '#ff7f0e', '#2ca02c'], backgroundColor: '#ffffff' }
const LABELS = Array.from({ length: 120 }, (_, i) => new Date(Date.UTC(2024, 0, 1 + i)).toISOString().slice(0, 10))
const value = (i: number, j: number): number => ((i * 7919 + j * 104729) % 1000) + 1
const SERIES: Series[] = Array.from({ length: 12 }, (_, s) => ({
    key: `s${s}`,
    label: `Series ${s}`,
    data: LABELS.map((_, i) => value(s, i)),
}))
const FIVE = SERIES.slice(0, 5)
const THREE = SERIES.slice(0, 3)
const PARTS: Series[] = SERIES.slice(0, 8).map((s) => ({ ...s, data: [s.data[0]] }))
const COMBO: Series[] = SERIES.slice(0, 6).map((s, i) => ({ ...s, type: i % 2 ? 'line' : 'bar' }))
const SLOPE_LABELS = ['Before', 'After']
const SLOPE: Series[] = SERIES.map((s) => ({ ...s, data: [s.data[0], s.data[1]] }))
const FUNNEL_STEPS = LABELS.slice(0, 6)
const BOX_LABELS = LABELS.slice(0, 30)
const BOX = THREE.map((s) => ({
    key: s.key,
    label: s.label,
    data: BOX_LABELS.map((_, i) => ({ min: 0, p25: 20 + (i % 5), median: 50, mean: 52, p75: 75, max: 100 })),
}))
const SCATTER = FIVE.map((s) => ({ key: s.key, label: s.label, points: s.data.map((y, x) => ({ x, y })) }))
const HEATMAP_X = LABELS.slice(0, 60)
const HEATMAP_Y = Array.from({ length: 20 }, (_, i) => `${i}ms`)
const CELLS = HEATMAP_Y.map((_, r) => HEATMAP_X.map((_, c) => value(r, c) % 10))
const STACKED_LABELS = LABELS.slice(0, 10)
const STACKED = THREE.map((s) => ({ ...s, data: s.data.slice(0, 10) }))
const NODES = Array.from({ length: 12 }, (_, i) => ({ id: `n${i}`, label: `Node ${i}` }))
const LINKS = Array.from({ length: 11 }, (_, i) => ({
    source: `n${Math.floor(i / 2)}`,
    target: `n${i + 1}`,
    value: 10 + i,
}))
const SPARK = SERIES[0].data
const rowLabel = (i: number): string => `Row ${i}`

let layoutChanges = 0
const LayoutProbe = React.memo(function LayoutProbe(): null {
    const layout = useChartLayout()
    const last = React.useRef<unknown>(null)
    if (layout !== last.current) {
        layoutChanges++
        last.current = layout
    }
    return null
})

// Each call builds fresh inline `config` literals over stable data, like a consumer that memoizes
// `series` and `labels` but not `config`.
const CHARTS: [string, () => React.ReactElement][] = [
    [
        'LineChart',
        () => (
            <LineChart series={SERIES} labels={LABELS} theme={THEME} config={{ showGrid: true }}>
                <LayoutProbe />
            </LineChart>
        ),
    ],
    [
        'LineChart percent',
        () => (
            <LineChart series={SERIES} labels={LABELS} theme={THEME} config={{ percentStackView: true }}>
                <LayoutProbe />
            </LineChart>
        ),
    ],
    [
        'BarChart',
        () => (
            <BarChart series={FIVE} labels={LABELS} theme={THEME} config={{ showGrid: true }}>
                <LayoutProbe />
            </BarChart>
        ),
    ],
    [
        'BarChart percent',
        () => (
            <BarChart series={FIVE} labels={LABELS} theme={THEME} config={{ barLayout: 'percent' }}>
                <LayoutProbe />
            </BarChart>
        ),
    ],
    [
        'BarChart horizontal',
        () => (
            <BarChart series={FIVE} labels={LABELS} theme={THEME} config={{ axisOrientation: 'horizontal' }}>
                <LayoutProbe />
            </BarChart>
        ),
    ],
    [
        'ComboChart',
        () => (
            <ComboChart series={COMBO} labels={LABELS} theme={THEME} config={{ showGrid: true }}>
                <LayoutProbe />
            </ComboChart>
        ),
    ],
    [
        'TimeSeriesLineChart',
        () => (
            <TimeSeriesLineChart series={SERIES} labels={LABELS} theme={THEME} config={{ showGrid: true }}>
                <LayoutProbe />
            </TimeSeriesLineChart>
        ),
    ],
    [
        'TimeSeriesBarChart',
        () => (
            <TimeSeriesBarChart series={FIVE} labels={LABELS} theme={THEME} config={{ showGrid: true }}>
                <LayoutProbe />
            </TimeSeriesBarChart>
        ),
    ],
    [
        'TimeSeriesComboChart',
        () => (
            <TimeSeriesComboChart series={COMBO} labels={LABELS} theme={THEME} config={{ showGrid: true }}>
                <LayoutProbe />
            </TimeSeriesComboChart>
        ),
    ],
    [
        'FunnelChart',
        () => (
            <FunnelChart steps={FUNNEL_STEPS} series={THREE} theme={THEME} config={{ showGrid: true }}>
                <LayoutProbe />
            </FunnelChart>
        ),
    ],
    [
        'ScatterChart',
        () => (
            <ScatterChart series={SCATTER} theme={THEME} config={{ showGrid: true }}>
                <LayoutProbe />
            </ScatterChart>
        ),
    ],
    [
        'BoxPlot',
        () => (
            <BoxPlot series={BOX} labels={BOX_LABELS} theme={THEME} config={{ showGrid: true }}>
                <LayoutProbe />
            </BoxPlot>
        ),
    ],
    [
        'Heatmap',
        () => (
            <Heatmap xLabels={HEATMAP_X} yLabels={HEATMAP_Y} cells={CELLS} theme={THEME} config={{}}>
                <LayoutProbe />
            </Heatmap>
        ),
    ],
    [
        'SlopeChart',
        () => (
            <SlopeChart series={SLOPE} labels={SLOPE_LABELS} theme={THEME} config={{}}>
                <LayoutProbe />
            </SlopeChart>
        ),
    ],
    [
        'PieChart',
        () => (
            <PieChart series={PARTS} theme={THEME} config={{}}>
                <LayoutProbe />
            </PieChart>
        ),
    ],
    ['ProportionBar', () => <ProportionBar series={PARTS} theme={THEME} config={{}} />],
    ['BarList', () => <BarList series={PARTS} theme={THEME} config={{ valueDisplay: 'both' }} />],
    [
        'StackedBarList',
        () => (
            <StackedBarList
                labels={STACKED_LABELS}
                series={STACKED}
                theme={THEME}
                config={{}}
                renderLabel={rowLabel}
                renderValue={rowLabel}
            >
                <LayoutProbe />
            </StackedBarList>
        ),
    ],
    ['SankeyChart', () => <SankeyChart nodes={NODES} links={LINKS} theme={THEME} config={{ showNodeValues: true }} />],
    ['Sparkline', () => <Sparkline data={SPARK} labels={LABELS} theme={THEME} />],
    [
        'MetricCard',
        () => <MetricCard title="Total" data={SPARK} labels={LABELS} theme={THEME} formatValue={(v) => `$${v}`} />,
    ],
]

interface Result {
    paintWrites: number
    layoutChanges: number
    hoverMs: number
    rerenderMs: number
}

const median = (values: number[]): number => [...values].sort((a, b) => a - b)[Math.floor(values.length / 2)]

describe('render cost', () => {
    const results: Record<string, Result> = {}

    afterAll(() => {
        // eslint-disable-next-line no-console
        console.table(results)
        if (process.env.BENCH_OUT) {
            writeFileSync(process.env.BENCH_OUT, JSON.stringify(results, null, 1))
        }
    })

    it.each(CHARTS)('%s', (name, ui) => {
        const { chart, rerender } = renderChart(ui())
        let paintWrites = 0
        const paints = new MutationObserver((records) => (paintWrites += records.length))
        paints.observe(chart.canvas, { attributeFilter: ['data-hog-charts-paint'] })
        // jest-canvas-mock logs every canvas call. Clear the logs each round, or the heap fills up.
        const clearCanvasLogs = (): void => {
            jest.clearAllMocks()
            chart.element.querySelectorAll('canvas').forEach((canvas) => {
                const ctx = canvas.getContext('2d') as unknown as Record<string, (() => void) | undefined>
                ctx.__clearEvents?.()
                ctx.__clearDrawCalls?.()
                ctx.__clearPath?.()
            })
        }
        layoutChanges = 0
        const hoverMs: number[] = []
        const rerenderMs: number[] = []

        for (let round = 0; round < ROUNDS; round++) {
            let start = performance.now()
            for (let i = 0; i < HOVERS_PER_ROUND; i++) {
                fireEvent.mouseMove(chart.element, { clientX: 20 + ((i * 37) % 760), clientY: 50 + ((i * 53) % 300) })
            }
            fireEvent.mouseLeave(chart.element)
            hoverMs.push((performance.now() - start) / (HOVERS_PER_ROUND + 1))
            clearCanvasLogs()

            start = performance.now()
            for (let i = 0; i < RERENDERS_PER_ROUND; i++) {
                act(() => rerender(ui()))
            }
            rerenderMs.push((performance.now() - start) / RERENDERS_PER_ROUND)
            clearCanvasLogs()
        }
        paintWrites += paints.takeRecords().length
        paints.disconnect()

        results[name] = {
            paintWrites,
            layoutChanges,
            hoverMs: +median(hoverMs).toFixed(3),
            rerenderMs: +median(rerenderMs).toFixed(3),
        }
    })
})
