import { Meta, StoryObj } from '@storybook/react'
import React, { useMemo, useState } from 'react'

import { BarChart } from '../../charts/BarChart/BarChart'
import { Heatmap } from '../../charts/Heatmap/Heatmap'
import { LineChart } from '../../charts/LineChart/LineChart'
import { TimeSeriesBarChart } from '../../charts/TimeSeriesBarChart/TimeSeriesBarChart'
import { TimeSeriesLineChart } from '../../charts/TimeSeriesLineChart/TimeSeriesLineChart'
import type { ChartGroupRange } from '../../core/chart-group'
import type { ChartTheme, Series } from '../../core/types'
import { useReactiveTheme } from '../../story-helpers'
import { MetricCard } from '../MetricCard/MetricCard'
import { ChartGroup } from './ChartGroup'

const meta: Meta = {
    title: 'Components/HogCharts/ChartGroup',
    parameters: { layout: 'padded' },
}
export default meta

type Story = StoryObj<{}>

const START = Date.UTC(2024, 4, 1, 10, 0)
const WINDOW_MS = 2 * 60 * 60 * 1000
const MINUTE = 60 * 1000

function seeded(seed: number): () => number {
    let state = seed
    return () => {
        state = (state * 1664525 + 1013904223) % 4294967296
        return state / 4294967296
    }
}

function buckets(stepMs: number): string[] {
    return Array.from({ length: WINDOW_MS / stepMs }, (_, i) => new Date(START + i * stepMs).toISOString())
}

// A latency incident between 11:10 and 11:25, so every chart has the same moment to line up on.
function incident(iso: string): number {
    const minutes = (Date.parse(iso) - START) / MINUTE
    return minutes >= 70 && minutes < 85 ? 1 : 0
}

const LATENCY_LABELS = buckets(MINUTE)
const ERROR_LABELS = buckets(5 * MINUTE)
const HEATMAP_LABELS = buckets(10 * MINUTE)
const REQUEST_LABELS = buckets(15 * MINUTE)
const DURATION_BUCKETS = ['<10ms', '10-25ms', '25-50ms', '50-100ms', '100-250ms', '250-500ms', '500ms-1s', '>1s']

function latencySeries(): Series[] {
    const random = seeded(7)
    const p50 = LATENCY_LABELS.map((l) => Math.round(42 + random() * 8 + incident(l) * 60))
    const p95 = LATENCY_LABELS.map((l, i) => Math.round(p50[i] * 2.4 + random() * 30 + incident(l) * 380))
    return [
        { key: 'p50', label: 'p50', data: p50 },
        { key: 'p95', label: 'p95', data: p95 },
    ]
}

function errorSeries(): Series[] {
    const random = seeded(11)
    return [
        { key: '5xx', label: '5xx', data: ERROR_LABELS.map((l) => Math.round(2 + random() * 4 + incident(l) * 48)) },
        { key: '4xx', label: '4xx', data: ERROR_LABELS.map(() => Math.round(10 + random() * 8)) },
    ]
}

function heatmapCells(): number[][] {
    const random = seeded(23)
    return DURATION_BUCKETS.map((_, row) =>
        HEATMAP_LABELS.map((l) => {
            const slow = incident(l) || incident(new Date(Date.parse(l) + 5 * MINUTE).toISOString())
            const peak = slow ? 5 : 2
            return Math.max(0, Math.round(400 * Math.exp(-((row - peak) ** 2) / 2) * (0.7 + random() * 0.6)))
        })
    )
}

function requestCounts(): number[] {
    const random = seeded(31)
    return REQUEST_LABELS.map((l) => Math.round(18000 + random() * 2500 - incident(l) * 3500))
}

/** Keeps the labels inside `[from, to)` along with the matching data, for a zoomed range. */
function sliceToRange(labels: string[], range: ChartGroupRange | null): [number, number] {
    if (!range || range.from == null || range.to == null) {
        return [0, labels.length]
    }
    const { from, to } = range
    const start = labels.findIndex((l) => Date.parse(l) >= from)
    const end = labels.findIndex((l) => Date.parse(l) >= to)
    return [Math.max(0, start), end < 0 ? labels.length : end]
}

function useSlice(labels: string[], range: ChartGroupRange | null): { labels: string[]; slice: <T>(a: T[]) => T[] } {
    return useMemo(() => {
        const [start, end] = sliceToRange(labels, range)
        return { labels: labels.slice(start, end), slice: (a) => a.slice(start, end) }
    }, [labels, range])
}

const formatTime = (iso: string): string => new Date(iso).toISOString().slice(11, 16)

function Tile({ title, children }: { title: string; children: React.ReactNode }): React.ReactElement {
    return (
        <div className="flex flex-col gap-2 h-60 rounded-lg border border-border bg-card p-3 min-w-0">
            <div className="text-xs font-medium text-muted-foreground truncate">{title}</div>
            <div className="relative flex flex-col flex-1 min-h-0">{children}</div>
        </div>
    )
}

interface DashboardProps {
    syncTooltip?: 'hovered' | 'all'
}

function Dashboard({ syncTooltip }: DashboardProps): React.ReactElement {
    const theme = useReactiveTheme()
    const [zoom, setZoom] = useState<ChartGroupRange | null>(null)
    const [selection, setSelection] = useState<ChartGroupRange | null>(null)

    const latency = useSlice(LATENCY_LABELS, zoom)
    const errors = useSlice(ERROR_LABELS, zoom)
    const heatmap = useSlice(HEATMAP_LABELS, zoom)
    const requests = useSlice(REQUEST_LABELS, zoom)

    const latencyData = useMemo(() => latencySeries().map((s) => ({ ...s, data: latency.slice(s.data) })), [latency])
    const errorData = useMemo(() => errorSeries().map((s) => ({ ...s, data: errors.slice(s.data) })), [errors])
    const cells = useMemo(() => heatmapCells().map((row) => heatmap.slice(row)), [heatmap])
    const requestData = useMemo(() => requests.slice(requestCounts()), [requests])

    return (
        <ChartGroup syncTooltip={syncTooltip} onZoom={setZoom} onSelectionChange={setSelection}>
            <div className="flex flex-col gap-3 w-full">
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground min-h-6">
                    <span>
                        Drag across any chart to zoom all of them. Brush the heatmap to mark a window on every chart;
                        Escape clears it.
                    </span>
                    {zoom && (
                        <button
                            type="button"
                            className="rounded border border-border px-2 py-0.5 text-foreground"
                            onClick={() => setZoom(null)}
                        >
                            Reset zoom
                        </button>
                    )}
                    {selection && (
                        <span className="font-mono">
                            Selected {formatTime(selection.startLabel)}–{formatTime(selection.endLabel)}
                        </span>
                    )}
                </div>
                <div className="grid gap-3 grid-cols-[repeat(auto-fill,minmax(min(100%,22rem),1fr))]">
                    <Tile title="Latency, 1 minute buckets">
                        <TimeSeriesLineChart
                            series={latencyData}
                            labels={latency.labels}
                            theme={theme}
                            config={{
                                xAxis: { timezone: 'UTC', interval: 'minute' },
                                yAxis: { format: 'duration_ms' },
                            }}
                        />
                    </Tile>
                    <Tile title="Errors, 5 minute buckets">
                        <TimeSeriesBarChart
                            series={errorData}
                            labels={errors.labels}
                            theme={theme}
                            config={{ xAxis: { timezone: 'UTC', interval: 'minute' }, barLayout: 'stacked' }}
                        />
                    </Tile>
                    <Tile title="Latency heatmap, 10 minute columns">
                        <Heatmap
                            xLabels={heatmap.labels}
                            yLabels={DURATION_BUCKETS}
                            cells={cells}
                            theme={theme}
                            config={{ xTickFormatter: formatTime, tooltip: { labelFormatter: formatTime } }}
                            onBrush={() => {}}
                        />
                    </Tile>
                    <div className="flex flex-col h-60 rounded-lg border border-border bg-card p-3 min-w-0">
                        <MetricCard
                            title="Requests, 15 minute buckets"
                            data={requestData}
                            labels={requests.labels}
                            formatLabel={formatTime}
                            restingSubtitle="Latest"
                            theme={theme}
                            sparklineFill
                            sparklineClassName="mt-3 -mx-3 -mb-3"
                            formatValue={(v) => Math.round(v).toLocaleString()}
                            headlineClassName="text-3xl"
                            className="flex-1 min-h-0"
                        />
                    </div>
                </div>
            </div>
        </ChartGroup>
    )
}

/** A latency line, an error bar chart, a latency heatmap and a stat tile, each at its own interval.
 *  Hover any of them and the others show the same moment. */
export const Dashboard_: Story = {
    name: 'Dashboard',
    render: () => <Dashboard />,
}

/** `syncTooltip: 'all'` opens every chart's tooltip at the hovered moment. */
export const SharedTooltips: Story = {
    render: () => <Dashboard syncTooltip="all" />,
}

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

/** Categorical charts line up when they share label strings. */
export const Categorical: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const signups: Series[] = [{ key: 'signups', label: 'Signups', data: [120, 180, 160, 210, 190, 90, 70] }]
        const revenue: Series[] = [{ key: 'revenue', label: 'Revenue', data: [3.1, 4.2, 3.9, 5.5, 4.8, 2.2, 1.9] }]
        return (
            <ChartGroup>
                <div className="grid gap-3 grid-cols-[repeat(auto-fill,minmax(min(100%,18rem),1fr))]">
                    <Tile title="Signups">
                        <BarChart series={signups} labels={WEEKDAYS} theme={theme} />
                    </Tile>
                    <Tile title="Revenue (k)">
                        <LineChart series={revenue} labels={WEEKDAYS} theme={theme} />
                    </Tile>
                </div>
            </ChartGroup>
        )
    },
}

const STRESS_INTERVALS = [MINUTE / 4, MINUTE / 2, MINUTE, 2 * MINUTE]

function stressChart(index: number, theme: ChartTheme): React.ReactElement {
    const step = STRESS_INTERVALS[index % STRESS_INTERVALS.length]
    const labels = buckets(step)
    const random = seeded(100 + index)
    let level = 50
    const series: Series[] = [0, 1].map((k) => ({
        key: `s${k}`,
        label: `Series ${k + 1}`,
        data: labels.map(() => {
            level = Math.max(1, level + (random() - 0.5) * 6)
            return Math.round(level * (k + 1))
        }),
    }))
    const title = `${labels.length} points, ${step / 1000}s buckets`
    return (
        <Tile key={index} title={title}>
            {index % 3 === 2 ? (
                <TimeSeriesBarChart
                    series={series}
                    labels={labels}
                    theme={theme}
                    config={{ xAxis: { timezone: 'UTC', interval: 'minute' } }}
                />
            ) : (
                <TimeSeriesLineChart
                    series={series}
                    labels={labels}
                    theme={theme}
                    config={{ xAxis: { timezone: 'UTC', interval: 'minute' } }}
                />
            )}
        </Tile>
    )
}

interface TwelveChartsArgs {
    grouped: boolean
    syncTooltip: 'hovered' | 'all'
}

/** Twelve charts with up to 480 points each, for profiling. Hover stays on the hover canvas: no chart
 *  but the hovered one re-renders, and no static canvas repaints. Turn `grouped` off for the baseline. */
export const TwelveCharts: StoryObj<TwelveChartsArgs> = {
    args: { grouped: true, syncTooltip: 'hovered' },
    argTypes: { syncTooltip: { control: 'inline-radio', options: ['hovered', 'all'] } },
    render: ({ grouped, syncTooltip }) => {
        const theme = useReactiveTheme()
        const grid = (
            <div className="grid gap-3 grid-cols-[repeat(auto-fill,minmax(min(100%,18rem),1fr))]">
                {Array.from({ length: 12 }, (_, i) => stressChart(i, theme))}
            </div>
        )
        return grouped ? <ChartGroup syncTooltip={syncTooltip}>{grid}</ChartGroup> : grid
    },
}
