import { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { Stage, useReactiveTheme } from '../../story-helpers'
import { ScatterChart } from './ScatterChart'
import type { ScatterAreaSelection, ScatterChartConfig, ScatterPoint, ScatterSeries } from './types'

// Deterministic pseudo-random spread, so visual snapshots are stable across runs.
function makeRandom(seed: number): () => number {
    let state = seed
    return () => {
        state = (state * 1103515245 + 12345) & 0x7fffffff
        return state / 0x7fffffff
    }
}

/** A correlated cloud: usage on x, activity on y, with enough scatter to be worth plotting. */
function makeCloud(count: number, seed: number, slope: number, spread: number): ScatterPoint[] {
    const next = makeRandom(seed)
    return Array.from({ length: count }, (_, i) => {
        const x = Math.round(next() * 900) + 20
        return {
            x,
            y: Math.max(1, Math.round(x * slope + (next() - 0.5) * spread)),
            label: `Org ${seed}-${i + 1}`,
        }
    })
}

const SINGLE: ScatterSeries[] = [{ key: 'orgs', label: 'Organizations', points: makeCloud(160, 1, 0.6, 260) }]

// Chrome is off by default in the library, so every story opts into `showGrid` the way the other
// chart types' stories do. `HostChrome` below shows what a product consumer sees instead.
const CHROME = { showGrid: true } satisfies ScatterChartConfig

const AXES = { ...CHROME, xAxis: { label: 'GB ingested' }, yAxis: { label: 'Queries run' } }

const meta: Meta<typeof ScatterChart> = {
    title: 'Charts/ScatterChart',
    component: ScatterChart,
    tags: ['autodocs'],
}
export default meta

type Story = StoryObj<typeof ScatterChart>

export const Default: Story = {
    render: function Render() {
        const theme = useReactiveTheme()
        return (
            <Stage width={620} height={360}>
                <ScatterChart series={SINGLE} theme={theme} config={AXES} />
            </Stage>
        )
    },
}

/** Several groups at once: color and marker shape both separate them, and the legend hides them. */
export const MultipleSeries: Story = {
    render: function Render() {
        const theme = useReactiveTheme()
        const series: ScatterSeries[] = [
            { key: 'enterprise', label: 'Enterprise', points: makeCloud(60, 3, 0.9, 200) },
            { key: 'scale', label: 'Scale', points: makeCloud(60, 7, 0.5, 200), shape: 'square' },
            { key: 'free', label: 'Free', points: makeCloud(60, 11, 0.2, 160), shape: 'cross' },
        ]
        return (
            <Stage width={620} height={380}>
                <ScatterChart series={series} theme={theme} config={{ ...AXES, legend: { show: true } }} />
            </Stage>
        )
    },
}

/** A dashed least-squares fit per series, over the same clouds `MultipleSeries` plots. */
export const BestFit: Story = {
    render: function Render() {
        const theme = useReactiveTheme()
        const series: ScatterSeries[] = [
            { key: 'enterprise', label: 'Enterprise', points: makeCloud(60, 3, 0.9, 200) },
            { key: 'free', label: 'Free', points: makeCloud(60, 11, 0.2, 160), shape: 'cross' },
        ]
        return (
            <Stage width={620} height={380}>
                <ScatterChart
                    series={series}
                    theme={theme}
                    config={{ ...AXES, showBestFit: true, legend: { show: true } }}
                />
            </Stage>
        )
    },
}

/** Heavy-tailed data — the reason both axes take a log scale. */
export const LogScales: Story = {
    render: function Render() {
        const theme = useReactiveTheme()
        const next = makeRandom(5)
        const points: ScatterPoint[] = Array.from({ length: 90 }, (_, i) => {
            const x = 10 ** (1 + next() * 3)
            return { x, y: Math.max(1, x ** 0.7 * (0.4 + next())), label: `Tenant ${i + 1}` }
        })
        return (
            <Stage width={620} height={360}>
                <ScatterChart
                    series={[{ key: 'tenants', label: 'Tenants', points }]}
                    theme={theme}
                    config={{
                        ...CHROME,
                        xAxis: { label: 'Rows stored', scaleType: 'log' },
                        yAxis: { label: 'Query cost', scaleType: 'log' },
                    }}
                />
            </Stage>
        )
    },
}

/** Cluster members plus an oversized centroid per cluster — per-point radius and color. */
export const ClustersWithCentroids: Story = {
    render: function Render() {
        const theme = useReactiveTheme()
        const centers = [
            [200, 700],
            [600, 250],
            [800, 800],
        ]
        const series: ScatterSeries[] = centers.map(([cx, cy], cluster) => {
            const next = makeRandom(cluster * 17 + 3)
            const members: ScatterPoint[] = Array.from({ length: 40 }, (_, i) => ({
                x: cx + (next() - 0.5) * 260,
                y: cy + (next() - 0.5) * 260,
                label: `Trace ${cluster + 1}-${i + 1}`,
            }))
            return {
                key: `cluster-${cluster}`,
                label: `Cluster ${cluster + 1}`,
                points: [...members, { x: cx, y: cy, label: `Cluster ${cluster + 1} centroid`, radius: 9 }],
            }
        })
        return (
            <Stage width={620} height={380}>
                <ScatterChart
                    series={series}
                    theme={theme}
                    config={{ ...CHROME, xAxis: { hide: true }, yAxis: { hide: true }, legend: { show: true } }}
                />
            </Stage>
        )
    },
}

/** Drag a rectangle to zoom; the button restores the data-derived domains. */
export const DragToZoom: Story = {
    // Skipped from visual regression: the selection rect only exists mid-drag, so a static snapshot
    // is Default again. The story stays for interactive documentation of onAreaSelect.
    tags: ['test-skip'],
    render: function Render() {
        const theme = useReactiveTheme()
        const [zoom, setZoom] = useState<ScatterAreaSelection | null>(null)
        return (
            <Stage width={620} height={380}>
                <ScatterChart
                    series={SINGLE}
                    theme={theme}
                    config={{
                        ...CHROME,
                        xAxis: { label: 'GB ingested', domain: zoom?.x },
                        yAxis: { label: 'Queries run', domain: zoom?.y },
                    }}
                    onAreaSelect={setZoom}
                />
                <button type="button" onClick={() => setZoom(null)} disabled={!zoom}>
                    Reset zoom
                </button>
            </Stage>
        )
    },
}

// The dashed grid and crosshair are theme rather than config, and the token vars carry no dash
// pattern: PostHog layers these on top in `chartThemeDefaults` (`frontend/src/lib/charts/hooks.ts`).
const HOST_THEME_CHROME = { gridDashPattern: [3, 3], crosshairDashPattern: [3, 3] }

/** The chart as PostHog renders it: every chrome toggle on, as a host's shared chart config defaults
 *  set them, over a theme carrying the host's dashed grid. */
export const HostChrome: Story = {
    render: function Render() {
        const theme = useReactiveTheme()
        return (
            <Stage width={620} height={360}>
                <ScatterChart
                    series={SINGLE}
                    theme={{ ...theme, ...HOST_THEME_CHROME }}
                    config={{
                        ...AXES,
                        showAxisLines: true,
                        showTickMarks: true,
                        showCrosshair: true,
                    }}
                />
            </Stage>
        )
    },
}

/** A degenerate domain: one point gives the axis no range to span. */
export const SinglePoint: Story = {
    // Skipped from visual regression: the degenerate-domain handling is `buildValueScale`'s, covered
    // in core/scales.test.ts. The story stays to show the result.
    tags: ['test-skip'],
    render: function Render() {
        const theme = useReactiveTheme()
        return (
            <Stage width={620} height={360}>
                <ScatterChart
                    series={[{ key: 'one', label: 'Only', points: [{ x: 42, y: 17, label: 'Only point' }] }]}
                    theme={theme}
                    config={AXES}
                />
            </Stage>
        )
    },
}

/** No series at all: the axes fall back to 0–1. */
export const Empty: Story = {
    // Skipped from visual regression: the empty-series fallback is `buildValueScale`'s, covered in
    // core/scales.test.ts.
    tags: ['test-skip'],
    render: function Render() {
        const theme = useReactiveTheme()
        return (
            <Stage width={620} height={360}>
                <ScatterChart series={[]} theme={theme} config={AXES} />
            </Stage>
        )
    },
}

/** Thousands of overlapping markers, which is what the translucent fill is for. */
export const DenseCloud: Story = {
    // Skipped from visual regression: Default already covers the translucent fill at the same
    // opacity, and 3000 markers make for a slow, jitter-prone screenshot.
    tags: ['test-skip'],
    render: function Render() {
        const theme = useReactiveTheme()
        const next = makeRandom(23)
        const points: ScatterPoint[] = Array.from({ length: 3000 }, () => {
            const x = next() * 1000
            return { x, y: x * 0.5 + (next() + next() + next() - 1.5) * 300 }
        })
        return (
            <Stage width={620} height={360}>
                <ScatterChart
                    series={[{ key: 'events', label: 'Events', points }]}
                    theme={theme}
                    config={{ ...AXES, pointRadius: 2.5 }}
                />
            </Stage>
        )
    },
}
