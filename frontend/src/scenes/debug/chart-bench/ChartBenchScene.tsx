import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { flushSync } from 'react-dom'

import { IconDatabaseBolt } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ChartJsLineChart } from './ChartJsLineChart'
import { generateBenchData } from './generateBenchData'
import { HogChartsLineChart } from './HogChartsLineChart'
import { RealAdaptersCell } from './RealAdaptersCell'

/**
 * Line-chart benchmark harness. Four chart "kinds":
 *
 *   - `hog`            — raw `lib/hog-charts` LineChart, synthetic data
 *   - `chartjs`        — raw chart.js Chart, synthetic data
 *   - `adapter-hog`    — real `TrendsLineChart` adapter fed through the
 *                        full insight kea logic tree (insight + data +
 *                        insightViz + trendsData) with cached results
 *   - `adapter-chartjs`— real `ActionsLineGraph` adapter (same logic tree,
 *                        chart.js under the hood)
 *
 * The raw cells isolate engine cost. The adapter cells include kea overhead,
 * the real PostHog tooltip (`TrendsTooltip` / `InsightTooltip`), and any
 * per-render selector/memoization cost — which is what actually ships.
 *
 * Results are exposed on `window.__chartBench` so a Playwright test can
 * iterate a matrix and compare.
 */

type ChartKind = 'hog' | 'chartjs' | 'adapter-hog' | 'adapter-chartjs'

interface BenchResult {
    chart: ChartKind
    series: number
    points: number
    seed: number
    runs: number
    /** Time from `flushSync(setRunKey)` through the next rAF — covers React
     * reconciliation, layout effects, paint, and any useEffect-scheduled draws. */
    readyMs: number[]
    /** Wall time for a 30-step mousemove sweep across the plot area. */
    hoverMs: number[]
    meanReadyMs: number
    meanHoverMs: number
}

declare global {
    interface Window {
        __chartBench?: BenchResult
    }
}

const CHART_OPTIONS: { label: string; value: ChartKind }[] = [
    { label: 'hog-charts (raw)', value: 'hog' },
    { label: 'chart.js (raw)', value: 'chartjs' },
    { label: 'hog-charts (TrendsLineChart adapter)', value: 'adapter-hog' },
    { label: 'chart.js (ActionsLineGraph adapter)', value: 'adapter-chartjs' },
]

const DEFAULT_SERIES = 10
const DEFAULT_POINTS = 500
const DEFAULT_RUNS = 5
const DEFAULT_SEED = 42

/** Pull a number out of URLSearchParams, falling back to a default. */
function readInt(params: URLSearchParams, key: string, fallback: number): number {
    const raw = params.get(key)
    if (raw == null) {
        return fallback
    }
    const parsed = Number.parseInt(raw, 10)
    return Number.isFinite(parsed) ? parsed : fallback
}

function mean(values: number[]): number {
    if (values.length === 0) {
        return 0
    }
    return values.reduce((a, b) => a + b, 0) / values.length
}

function round(n: number): number {
    return Math.round(n * 100) / 100
}

/** Waits for a single animation frame, returning the elapsed ms. */
function nextFrame(): Promise<number> {
    return new Promise((resolve) => {
        const start = performance.now()
        requestAnimationFrame(() => {
            resolve(performance.now() - start)
        })
    })
}

interface ChartCellProps {
    chart: ChartKind
    series: number
    points: number
    seed: number
    fillArea: boolean
    showGrid: boolean
    runKey: number
}

function ChartCell({ chart, series, points, seed, fillArea, showGrid, runKey }: ChartCellProps): JSX.Element {
    const data = useMemo(() => generateBenchData(series, points, seed), [series, points, seed])
    if (chart === 'hog') {
        return <HogChartsLineChart data={data} fillArea={fillArea} showGrid={showGrid} />
    }
    if (chart === 'chartjs') {
        return <ChartJsLineChart data={data} fillArea={fillArea} showGrid={showGrid} />
    }
    return <RealAdaptersCell kind={chart} data={data} runKey={runKey} fillArea={fillArea} />
}

export function ChartBenchScene(): JSX.Element {
    const initialParams = useMemo(() => new URLSearchParams(window.location.search), [])

    const [chart, setChart] = useState<ChartKind>((initialParams.get('chart') as ChartKind) || 'hog')
    const [seriesCount, setSeriesCount] = useState<number>(readInt(initialParams, 'series', DEFAULT_SERIES))
    const [pointCount, setPointCount] = useState<number>(readInt(initialParams, 'points', DEFAULT_POINTS))
    const [runs, setRuns] = useState<number>(readInt(initialParams, 'runs', DEFAULT_RUNS))
    const [seed, setSeed] = useState<number>(readInt(initialParams, 'seed', DEFAULT_SEED))
    const [fillArea, setFillArea] = useState<boolean>(initialParams.get('fill') === '1')
    const [showGrid, setShowGrid] = useState<boolean>(initialParams.get('grid') !== '0')

    const [runKey, setRunKey] = useState<number>(0)
    const [result, setResult] = useState<BenchResult | null>(null)
    const [busy, setBusy] = useState<boolean>(false)

    const containerRef = useRef<HTMLDivElement>(null)

    /** Locate the canvas the current chart cell rendered. Both cells wrap their
     * canvas in a div with a stable `data-attr`. */
    const findCanvas = useCallback((): HTMLCanvasElement | null => {
        if (!containerRef.current) {
            return null
        }
        return containerRef.current.querySelector('canvas')
    }, [])

    /** Dispatch mousemove events across the chart's plot area and sum the
     * per-step frame time. This approximates real hover cost — both the chart
     * engine's hit-test and its redraw/tooltip work. */
    const sweepHover = useCallback(async (): Promise<number> => {
        const canvas = findCanvas()
        if (!canvas) {
            return 0
        }
        const rect = canvas.getBoundingClientRect()
        const steps = 30
        let total = 0
        for (let i = 0; i < steps; i++) {
            const x = rect.left + (rect.width * (i + 0.5)) / steps
            const y = rect.top + rect.height / 2
            canvas.dispatchEvent(
                new MouseEvent('mousemove', {
                    bubbles: true,
                    cancelable: true,
                    clientX: x,
                    clientY: y,
                    view: window,
                })
            )
            total += await nextFrame()
        }
        // Reset with a mouseleave so the next run starts clean.
        canvas.dispatchEvent(new MouseEvent('mouseleave', { bubbles: true, cancelable: true }))
        return total
    }, [findCanvas])

    const runBenchmark = useCallback(async () => {
        setBusy(true)
        const readySamples: number[] = []
        const hoverSamples: number[] = []

        for (let i = 0; i < runs; i++) {
            const t0 = performance.now()
            // flushSync forces the remount and all layout effects to run
            // synchronously before returning. For chart.js this includes the
            // constructor + draw because ChartJsLineChart uses useLayoutEffect.
            // For hog-charts the draw is in a useEffect (post-paint), so we
            // wait one rAF to include it in the measurement.
            flushSync(() => setRunKey((k) => k + 1))
            await nextFrame()
            readySamples.push(performance.now() - t0)

            hoverSamples.push(await sweepHover())
            // Small breather between runs so any async work settles.
            await new Promise((r) => setTimeout(r, 16))
        }

        const finalResult: BenchResult = {
            chart,
            series: seriesCount,
            points: pointCount,
            seed,
            runs,
            readyMs: readySamples,
            hoverMs: hoverSamples,
            meanReadyMs: round(mean(readySamples)),
            meanHoverMs: round(mean(hoverSamples)),
        }
        window.__chartBench = finalResult
        setResult(finalResult)
        setBusy(false)
    }, [chart, seriesCount, pointCount, seed, runs, sweepHover])

    // Keep the URL in sync with the controls so benchmark runs are shareable
    // and Playwright can parameterize via query string.
    useEffect(() => {
        const params = new URLSearchParams()
        params.set('chart', chart)
        params.set('series', String(seriesCount))
        params.set('points', String(pointCount))
        params.set('runs', String(runs))
        params.set('seed', String(seed))
        if (fillArea) {
            params.set('fill', '1')
        }
        if (!showGrid) {
            params.set('grid', '0')
        }
        const next = `${window.location.pathname}?${params.toString()}`
        if (next !== window.location.pathname + window.location.search) {
            window.history.replaceState(null, '', next)
        }
    }, [chart, seriesCount, pointCount, runs, seed, fillArea, showGrid])

    return (
        <SceneContent className="ChartBenchScene">
            <SceneTitleSection
                name="Chart benchmark"
                description="Compare hog-charts vs chart.js rendering cost for line charts."
                resourceType={{ type: 'debug', forceIcon: <IconDatabaseBolt /> }}
            />
            <div className="flex flex-wrap gap-4 items-end">
                <div>
                    <LemonLabel>Chart</LemonLabel>
                    <LemonSelect value={chart} options={CHART_OPTIONS} onChange={(v) => setChart(v)} />
                </div>
                <div>
                    <LemonLabel>Series</LemonLabel>
                    <LemonInput
                        type="number"
                        value={seriesCount}
                        min={1}
                        max={200}
                        onChange={(v) => setSeriesCount(Number(v) || 1)}
                    />
                </div>
                <div>
                    <LemonLabel>Points</LemonLabel>
                    <LemonInput
                        type="number"
                        value={pointCount}
                        min={2}
                        max={5000}
                        onChange={(v) => setPointCount(Number(v) || 2)}
                    />
                </div>
                <div>
                    <LemonLabel>Runs</LemonLabel>
                    <LemonInput type="number" value={runs} min={1} max={50} onChange={(v) => setRuns(Number(v) || 1)} />
                </div>
                <div>
                    <LemonLabel>Seed</LemonLabel>
                    <LemonInput type="number" value={seed} onChange={(v) => setSeed(Number(v) || 0)} />
                </div>
                <LemonSwitch label="Fill area" checked={fillArea} onChange={setFillArea} />
                <LemonSwitch
                    label="Grid"
                    checked={showGrid}
                    onChange={setShowGrid}
                    // The grid toggle only affects the raw cells — adapter
                    // modes always draw a grid (hog-charts sets `showGrid:true`
                    // inside TrendsLineChart, chart.js draws grid by default).
                    disabledReason={
                        chart.startsWith('adapter-')
                            ? 'Grid is baked into the adapter at this size — raw cells only'
                            : undefined
                    }
                />
                <LemonButton type="primary" onClick={runBenchmark} loading={busy} data-attr="chart-bench-run">
                    Run benchmark
                </LemonButton>
            </div>

            <div
                ref={containerRef}
                className="border rounded bg-bg-light flex flex-col"
                // Fixed size so repeated runs compare apples-to-apples. Flex
                // column because hog-charts' internal wrapper uses `flex: 1`.
                style={{ width: 960, height: 480 }}
                data-attr="chart-bench-stage"
            >
                <ChartCell
                    key={`${chart}-${runKey}`}
                    chart={chart}
                    series={seriesCount}
                    points={pointCount}
                    seed={seed}
                    fillArea={fillArea}
                    showGrid={showGrid}
                    runKey={runKey}
                />
            </div>

            {result ? (
                <div className="font-mono text-sm" data-attr="chart-bench-result">
                    <div>
                        chart: <strong>{result.chart}</strong> · series {result.series} · points {result.points} · runs{' '}
                        {result.runs}
                    </div>
                    <div>mean ready (mount → post-paint): {result.meanReadyMs} ms</div>
                    <div>mean hover sweep (30 moves): {result.meanHoverMs} ms</div>
                </div>
            ) : null}
        </SceneContent>
    )
}

export const scene: SceneExport = {
    component: ChartBenchScene,
}
