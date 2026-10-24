import { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { Stage, useReactiveTheme } from '../../story-helpers'
import { Histogram } from './Histogram'
import type { HistogramBin, HistogramRange, HistogramSeries } from './types'

const MS = 1_000_000

// 1-2-5 log buckets from 100µs to 20s in nanoseconds, the shape tracing's duration histogram uses.
const EDGES_NS: number[] = []
for (let decade = 100_000; decade <= 10_000_000_000; decade *= 10) {
    EDGES_NS.push(decade, decade * 2, decade * 5)
}
EDGES_NS.push(20_000_000_000)

// A log-normal body around 30ms plus a slow tail and a timeout spike at 5s: deterministic, and
// shaped like a real service with a cache in front of a slow dependency.
function density(midNs: number, centerNs: number, spread: number, peak: number): number {
    const z = (Math.log(midNs) - Math.log(centerNs)) / spread
    return peak * Math.exp(-0.5 * z * z)
}

const OK_COUNTS = EDGES_NS.slice(0, -1).map((start, i) => {
    const mid = Math.sqrt(start * EDGES_NS[i + 1])
    return Math.round(density(mid, 30 * MS, 0.9, 4200) + density(mid, 900 * MS, 0.6, 260))
})
const ERROR_COUNTS = EDGES_NS.slice(0, -1).map((start, i) => {
    const mid = Math.sqrt(start * EDGES_NS[i + 1])
    return Math.round(density(mid, 1.5 * MS, 0.5, 90) + density(mid, 5_000 * MS, 0.2, 140))
})

const LATENCY_BINS: HistogramBin[] = EDGES_NS.slice(0, -1).map((start, i) => ({
    start,
    end: EDGES_NS[i + 1],
    count: OK_COUNTS[i] + ERROR_COUNTS[i],
}))

const STACKED_SERIES: HistogramSeries[] = [
    { key: 'ok', label: 'OK', data: OK_COUNTS },
    { key: 'error', label: 'Error', data: ERROR_COUNTS, color: 'var(--data-color-5)' },
]

const DURATION_AXIS = { scale: 'log', format: 'duration_ns', label: 'Duration' } as const

const meta: Meta<typeof Histogram> = {
    title: 'Charts/Histogram',
    component: Histogram,
    tags: ['autodocs'],
}
export default meta

type Story = StoryObj<typeof Histogram>

export const LatencyLogBuckets: Story = {
    render: function Render() {
        const theme = useReactiveTheme()
        return (
            <Stage width={720} height={280}>
                <Histogram bins={LATENCY_BINS} theme={theme} config={{ xAxis: DURATION_AXIS }} />
            </Stage>
        )
    },
}

export const StackedOkAndError: Story = {
    render: function Render() {
        const theme = useReactiveTheme()
        return (
            <Stage width={720} height={300}>
                <Histogram
                    bins={LATENCY_BINS}
                    series={STACKED_SERIES}
                    theme={theme}
                    config={{ xAxis: DURATION_AXIS, legend: { show: true, position: 'top', align: 'end' } }}
                />
            </Stage>
        )
    },
}

export const PercentileMarkers: Story = {
    render: function Render() {
        const theme = useReactiveTheme()
        return (
            <Stage width={720} height={280}>
                <Histogram
                    bins={LATENCY_BINS}
                    theme={theme}
                    config={{
                        xAxis: DURATION_AXIS,
                        markers: [{ percentile: 50 }, { percentile: 95 }, { percentile: 99 }],
                    }}
                />
            </Stage>
        )
    },
}

export const RangeSelection: Story = {
    render: function Render() {
        const theme = useReactiveTheme()
        const [range, setRange] = useState<HistogramRange | null>({ min: 200 * MS, max: 2_000 * MS })
        return (
            <Stage width={720} height={280}>
                <Histogram
                    bins={LATENCY_BINS}
                    series={STACKED_SERIES}
                    theme={theme}
                    config={{ xAxis: DURATION_AXIS }}
                    selectedRange={range}
                    onRangeSelect={setRange}
                    onRangeClear={() => setRange(null)}
                />
            </Stage>
        )
    },
}

export const LogCountAxis: Story = {
    render: function Render() {
        const theme = useReactiveTheme()
        return (
            <Stage width={720} height={280}>
                <Histogram
                    bins={LATENCY_BINS}
                    series={STACKED_SERIES}
                    theme={theme}
                    config={{ xAxis: DURATION_AXIS, yAxis: { scale: 'log' } }}
                />
            </Stage>
        )
    },
}

// Equal-width bins on a linear axis, starting at zero: the textbook histogram.
const LINEAR_BINS: HistogramBin[] = Array.from({ length: 40 }, (_, i) => ({
    start: i * 25,
    end: (i + 1) * 25,
    count: Math.round(density((i + 0.5) * 25, 300, 0.45, 800)),
}))

export const LinearBins: Story = {
    render: function Render() {
        const theme = useReactiveTheme()
        return (
            <Stage width={720} height={280}>
                <Histogram
                    bins={LINEAR_BINS}
                    theme={theme}
                    config={{
                        xAxis: { format: 'duration_ms', label: 'Response time' },
                        markers: [{ percentile: 50 }, { value: 600, label: 'SLO' }],
                    }}
                />
            </Stage>
        )
    },
}

const MANY_BINS: HistogramBin[] = Array.from({ length: 1200 }, (_, i) => {
    const start = Math.pow(10, 5 + (i / 1200) * 5)
    const end = Math.pow(10, 5 + ((i + 1) / 1200) * 5)
    const mid = Math.sqrt(start * end)
    return { start, end, count: Math.round(density(mid, 25 * MS, 0.8, 900) + density(mid, 700 * MS, 0.5, 120)) }
})

export const ThousandsOfBins: Story = {
    render: function Render() {
        const theme = useReactiveTheme()
        return (
            <Stage width={720} height={280}>
                <Histogram bins={MANY_BINS} theme={theme} config={{ xAxis: DURATION_AXIS }} />
            </Stage>
        )
    },
}

export const Narrow: Story = {
    render: function Render() {
        const theme = useReactiveTheme()
        const [range, setRange] = useState<HistogramRange | null>({ min: 20 * MS, max: 200 * MS })
        return (
            <Stage width={360} height={220}>
                <Histogram
                    bins={LATENCY_BINS}
                    series={STACKED_SERIES}
                    theme={theme}
                    config={{ xAxis: DURATION_AXIS, markers: [{ percentile: 50 }, { percentile: 99 }] }}
                    selectedRange={range}
                    onRangeSelect={setRange}
                    onRangeClear={() => setRange(null)}
                />
            </Stage>
        )
    },
}

export const EdgeCases: Story = {
    render: function Render() {
        const theme = useReactiveTheme()
        return (
            <div className="grid grid-cols-2 gap-4">
                <Stage width={340} height={180}>
                    <Histogram bins={[{ start: 0, end: 10, count: 7 }]} theme={theme} />
                </Stage>
                <Stage width={340} height={180}>
                    <Histogram bins={LINEAR_BINS.map((bin) => ({ ...bin, count: 0 }))} theme={theme} />
                </Stage>
                <Stage width={340} height={180}>
                    <Histogram
                        bins={[
                            { start: 0, end: 1 * MS, count: 40 },
                            { start: 5 * MS, end: 10 * MS, count: 12 },
                            { start: 1 * MS, end: 5 * MS, count: 95 },
                            { start: 50 * MS, end: 100 * MS, count: 3 },
                        ]}
                        theme={theme}
                        config={{ xAxis: { scale: 'log', format: 'duration_ns' } }}
                    />
                </Stage>
                <Stage width={340} height={180}>
                    <Histogram
                        bins={LINEAR_BINS.map((bin, i) => ({ ...bin, count: i === 12 ? 250_000 : bin.count }))}
                        theme={theme}
                    />
                </Stage>
            </div>
        )
    },
}
