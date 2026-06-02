import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { flushSync } from 'react-dom'

import { IconDatabaseBolt } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ChartJsLineChart } from './ChartJsLineChart'
import { generateBenchData } from './generateBenchData'
import { HogChartsBarChart } from './HogChartsBarChart'
import { HogChartsLineChart } from './HogChartsLineChart'
import { RealAdaptersCell } from './RealAdaptersCell'
import { SweepResultsChart } from './SweepResultsChart'
import type { ChartKind as SweepChartKind, SweepResult } from './sweepTypes'

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

type ChartKind = SweepChartKind

export interface BenchResult {
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
    meanHoverSyncMs: number
    meanHoverFrameMs: number
}

declare global {
    interface Window {
        __chartBench?: BenchResult
    }
}

const CHART_OPTIONS: { label: string; value: ChartKind }[] = [
    { label: 'hog-charts line (raw)', value: 'hog' },
    { label: 'chart.js line (raw)', value: 'chartjs' },
    { label: 'hog-charts bar (raw)', value: 'hog-bar' },
    { label: 'hog-charts (TrendsLineChart adapter)', value: 'adapter-hog' },
    { label: 'chart.js (ActionsLineGraph adapter)', value: 'adapter-chartjs' },
    { label: 'hog-charts (TrendsBarChart adapter)', value: 'adapter-bar' },
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
    const valid = values.filter((v) => Number.isFinite(v))
    if (valid.length === 0) {
        return NaN
    }
    return valid.reduce((a, b) => a + b, 0) / valid.length
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

/** Log-spaced integers between min and max inclusive, deduplicated. */
function logSpace(min: number, max: number, steps: number): number[] {
    const lo = Math.max(2, Math.floor(min))
    const hi = Math.max(lo + 1, Math.floor(max))
    if (steps <= 1) {
        return [lo]
    }
    const lmin = Math.log10(lo)
    const lmax = Math.log10(hi)
    const seen = new Set<number>()
    const out: number[] = []
    for (let i = 0; i < steps; i++) {
        const t = i / (steps - 1)
        const v = Math.round(Math.pow(10, lmin + (lmax - lmin) * t))
        if (!seen.has(v)) {
            seen.add(v)
            out.push(v)
        }
    }
    return out
}

function parseSeriesList(raw: string): number[] {
    return raw
        .split(',')
        .map((s) => Number.parseInt(s.trim(), 10))
        .filter((n) => Number.isFinite(n) && n > 0)
}

const ALL_CHART_KINDS: ChartKind[] = ['hog', 'chartjs', 'hog-bar', 'adapter-hog', 'adapter-chartjs', 'adapter-bar']

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
    if (chart === 'hog-bar') {
        return <HogChartsBarChart data={data} showGrid={showGrid} />
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

    const [sweepMin, setSweepMin] = useState<number>(10)
    const [sweepMax, setSweepMax] = useState<number>(100_000)
    const [sweepSteps, setSweepSteps] = useState<number>(10)
    const [sweepSeriesList, setSweepSeriesList] = useState<string>('1, 10')
    const [sweepKinds, setSweepKinds] = useState<ChartKind[]>(['hog', 'chartjs'])
    const [sweepRuns, setSweepRuns] = useState<number>(3)
    const [sweepLogY, setSweepLogY] = useState<boolean>(true)
    const [sweepResults, setSweepResults] = useState<SweepResult[]>([])
    const [sweepProgress, setSweepProgress] = useState<{ done: number; total: number; label: string } | null>(null)
    const sweepAbortRef = useRef<boolean>(false)

    const containerRef = useRef<HTMLDivElement>(null)

    /** Locate the canvas the current chart cell rendered. Both cells wrap their
     * canvas in a div with a stable `data-attr`. */
    const findCanvas = useCallback((): HTMLCanvasElement | null => {
        if (!containerRef.current) {
            return null
        }
        return containerRef.current.querySelector('canvas')
    }, [])

    /** Dispatch hover events across the chart's plot area, capturing both the
     * synchronous dispatch time (React handler + setState + sync effects) and
     * the frame-wait time after dispatch returns. Splitting them out makes it
     * possible to tell whether a slow cell is bottlenecked in JS or in paint.
     * Both `pointermove` and `mousemove` are dispatched — chart.js listens on
     * pointer events, hog-charts on mouse events. Sync/frame are NaN if the
     * canvas wasn't actually sized when the run started. */
    const sweepHover = useCallback(async (): Promise<{ total: number; sync: number; frame: number }> => {
        const canvas = findCanvas()
        if (!canvas) {
            return { total: NaN, sync: NaN, frame: NaN }
        }
        const rect = canvas.getBoundingClientRect()
        if (rect.width < 10 || rect.height < 10) {
            return { total: NaN, sync: NaN, frame: NaN }
        }
        const steps = 30
        let totalSync = 0
        let totalFrame = 0
        for (let i = 0; i < steps; i++) {
            const x = rect.left + (rect.width * (i + 0.5)) / steps
            const y = rect.top + rect.height / 2
            const init: PointerEventInit = {
                bubbles: true,
                cancelable: true,
                clientX: x,
                clientY: y,
                view: window,
                pointerType: 'mouse',
            }
            const dispatchStart = performance.now()
            canvas.dispatchEvent(new PointerEvent('pointermove', init))
            canvas.dispatchEvent(new MouseEvent('mousemove', init))
            totalSync += performance.now() - dispatchStart
            totalFrame += await nextFrame()
        }
        canvas.dispatchEvent(
            new PointerEvent('pointerleave', { bubbles: true, cancelable: true, pointerType: 'mouse' })
        )
        canvas.dispatchEvent(new MouseEvent('mouseleave', { bubbles: true, cancelable: true }))
        return { total: totalSync + totalFrame, sync: totalSync, frame: totalFrame }
    }, [findCanvas])

    const runBenchmark = useCallback(async () => {
        setBusy(true)
        const readySamples: number[] = []
        const hoverSamples: number[] = []
        const hoverSyncSamples: number[] = []
        const hoverFrameSamples: number[] = []

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

            const hover = await sweepHover()
            hoverSamples.push(hover.total)
            hoverSyncSamples.push(hover.sync)
            hoverFrameSamples.push(hover.frame)
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
            meanHoverSyncMs: round(mean(hoverSyncSamples)),
            meanHoverFrameMs: round(mean(hoverFrameSamples)),
        }
        window.__chartBench = finalResult
        setResult(finalResult)
        setBusy(false)
    }, [chart, seriesCount, pointCount, seed, runs, sweepHover])

    const runSweep = useCallback(async () => {
        const seriesValues = parseSeriesList(sweepSeriesList)
        const pointValues = logSpace(sweepMin, sweepMax, sweepSteps)
        if (sweepKinds.length === 0 || seriesValues.length === 0 || pointValues.length === 0) {
            return
        }
        const cells: { chart: ChartKind; series: number; points: number }[] = []
        for (const ck of sweepKinds) {
            for (const sv of seriesValues) {
                for (const pv of pointValues) {
                    cells.push({ chart: ck, series: sv, points: pv })
                }
            }
        }

        sweepAbortRef.current = false
        setBusy(true)
        setSweepResults([])
        setSweepProgress({ done: 0, total: cells.length, label: '' })

        const collected: SweepResult[] = []
        for (let idx = 0; idx < cells.length; idx++) {
            if (sweepAbortRef.current) {
                break
            }
            const cell = cells[idx]
            setSweepProgress({
                done: idx,
                total: cells.length,
                label: `${cell.chart} · ${cell.series}s × ${cell.points}p`,
            })

            // Drive the visible cell to this matrix point. flushSync forces
            // React to commit before we measure, and the runKey bump produces
            // fresh logic instances for the adapter cells.
            flushSync(() => {
                setChart(cell.chart)
                setSeriesCount(cell.series)
                setPointCount(cell.points)
                setRunKey((k) => k + 1)
            })
            // Two frames: first to mount/draw, second to ensure any post-paint
            // chart engine work has settled before we start measuring.
            await nextFrame()
            await nextFrame()

            const readySamples: number[] = []
            const hoverSamples: number[] = []
            const hoverSyncSamples: number[] = []
            const hoverFrameSamples: number[] = []
            for (let i = 0; i < sweepRuns; i++) {
                if (sweepAbortRef.current) {
                    break
                }
                const t0 = performance.now()
                flushSync(() => setRunKey((k) => k + 1))
                await nextFrame()
                readySamples.push(performance.now() - t0)
                const hover = await sweepHover()
                hoverSamples.push(hover.total)
                hoverSyncSamples.push(hover.sync)
                hoverFrameSamples.push(hover.frame)
                await new Promise((r) => setTimeout(r, 16))
            }

            const cellResult: SweepResult = {
                chart: cell.chart,
                series: cell.series,
                points: cell.points,
                runs: readySamples.length,
                meanReadyMs: round(mean(readySamples)),
                meanHoverMs: round(mean(hoverSamples)),
                meanHoverSyncMs: round(mean(hoverSyncSamples)),
                meanHoverFrameMs: round(mean(hoverFrameSamples)),
                readyMs: readySamples,
                hoverMs: hoverSamples,
            }
            collected.push(cellResult)
            setSweepResults([...collected])
        }

        setSweepProgress(null)
        setBusy(false)
    }, [sweepMin, sweepMax, sweepSteps, sweepSeriesList, sweepKinds, sweepRuns, sweepHover])

    const stopSweep = useCallback(() => {
        sweepAbortRef.current = true
    }, [])

    const exportSweep = useCallback(() => {
        if (sweepResults.length === 0) {
            return
        }
        const blob = new Blob([JSON.stringify(sweepResults, null, 2)], { type: 'application/json' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `chart-bench-sweep-${Date.now()}.json`
        a.click()
        URL.revokeObjectURL(url)
    }, [sweepResults])

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
                        max={1_000_000}
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
                    <div>
                        mean hover sweep (30 moves): {result.meanHoverMs} ms (sync {result.meanHoverSyncMs} ms · frame{' '}
                        {result.meanHoverFrameMs} ms)
                    </div>
                </div>
            ) : null}

            <div className="border-t pt-4 mt-4">
                <h3 className="text-base font-semibold mb-2">Parameter sweep</h3>
                <div className="text-xs text-muted mb-3">
                    Walks a log-spaced grid of point counts × series counts × chart kinds, running the benchmark for
                    each cell and plotting the results. Chart container above is reused for each measurement.
                </div>
                <div className="flex flex-wrap gap-4 items-end">
                    <div>
                        <LemonLabel>Min points</LemonLabel>
                        <LemonInput
                            type="number"
                            value={sweepMin}
                            min={2}
                            onChange={(v) => setSweepMin(Number(v) || 2)}
                        />
                    </div>
                    <div>
                        <LemonLabel>Max points</LemonLabel>
                        <LemonInput
                            type="number"
                            value={sweepMax}
                            min={2}
                            onChange={(v) => setSweepMax(Number(v) || 2)}
                        />
                    </div>
                    <div>
                        <LemonLabel>Steps</LemonLabel>
                        <LemonInput
                            type="number"
                            value={sweepSteps}
                            min={2}
                            max={50}
                            onChange={(v) => setSweepSteps(Number(v) || 2)}
                        />
                    </div>
                    <div>
                        <LemonLabel>Series (comma-separated)</LemonLabel>
                        <LemonInput value={sweepSeriesList} onChange={(v) => setSweepSeriesList(v)} />
                    </div>
                    <div>
                        <LemonLabel>Runs / cell</LemonLabel>
                        <LemonInput
                            type="number"
                            value={sweepRuns}
                            min={1}
                            max={20}
                            onChange={(v) => setSweepRuns(Number(v) || 1)}
                        />
                    </div>
                    <LemonSwitch label="Log Y" checked={sweepLogY} onChange={setSweepLogY} />
                </div>
                <div className="flex flex-wrap gap-4 items-center mt-2">
                    <span className="text-sm text-muted">Charts:</span>
                    {ALL_CHART_KINDS.map((k) => (
                        <LemonCheckbox
                            key={k}
                            label={k}
                            checked={sweepKinds.includes(k)}
                            onChange={(checked) =>
                                setSweepKinds((prev) => (checked ? [...prev, k] : prev.filter((p) => p !== k)))
                            }
                        />
                    ))}
                </div>
                <div className="flex flex-wrap gap-2 items-center mt-3">
                    <LemonButton
                        type="primary"
                        onClick={runSweep}
                        loading={busy && !!sweepProgress}
                        disabledReason={
                            sweepKinds.length === 0
                                ? 'Pick at least one chart'
                                : parseSeriesList(sweepSeriesList).length === 0
                                  ? 'Series list is empty'
                                  : undefined
                        }
                        data-attr="chart-bench-sweep-run"
                    >
                        Run sweep
                    </LemonButton>
                    {sweepProgress ? (
                        <LemonButton type="secondary" onClick={stopSweep}>
                            Stop
                        </LemonButton>
                    ) : null}
                    {sweepResults.length > 0 ? (
                        <LemonButton type="secondary" onClick={exportSweep}>
                            Export JSON
                        </LemonButton>
                    ) : null}
                    {sweepProgress ? (
                        <span className="font-mono text-xs">
                            {sweepProgress.done}/{sweepProgress.total} — {sweepProgress.label}
                        </span>
                    ) : null}
                    {!sweepProgress && sweepResults.length > 0 ? (
                        <span className="font-mono text-xs text-muted">
                            {sweepResults.length} cells · grid: {logSpace(sweepMin, sweepMax, sweepSteps).join(', ')}
                        </span>
                    ) : null}
                </div>

                {sweepResults.length > 0
                    ? Array.from(new Set(sweepResults.map((r) => r.series)))
                          .sort((a, b) => a - b)
                          .map((seriesCount) => {
                              const filtered = sweepResults.filter((r) => r.series === seriesCount)
                              return (
                                  <div key={seriesCount} className="mt-6">
                                      <h4 className="text-sm font-semibold mb-2">{seriesCount} series</h4>
                                      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                                          <SweepResultsChart
                                              results={filtered}
                                              metric="meanReadyMs"
                                              title="Mount → post-paint (ms)"
                                              logY={sweepLogY}
                                          />
                                          <SweepResultsChart
                                              results={filtered}
                                              metric="meanHoverMs"
                                              title="Hover sweep, 30 moves (ms)"
                                              logY={sweepLogY}
                                          />
                                      </div>
                                  </div>
                              )
                          })
                    : null}

                {sweepResults.length > 0 ? (
                    <details className="mt-4">
                        <summary className="text-sm cursor-pointer">Raw table ({sweepResults.length} rows)</summary>
                        <table className="font-mono text-xs mt-2">
                            <thead>
                                <tr>
                                    <th className="text-left pr-4">chart</th>
                                    <th className="text-right pr-4">series</th>
                                    <th className="text-right pr-4">points</th>
                                    <th className="text-right pr-4">ready ms</th>
                                    <th className="text-right pr-4">hover ms</th>
                                </tr>
                            </thead>
                            <tbody>
                                {sweepResults.map((r, i) => (
                                    <tr key={i}>
                                        <td className="pr-4">{r.chart}</td>
                                        <td className="text-right pr-4">{r.series}</td>
                                        <td className="text-right pr-4">{r.points}</td>
                                        <td className="text-right pr-4">
                                            {Number.isFinite(r.meanReadyMs) ? r.meanReadyMs : '—'}
                                        </td>
                                        <td className="text-right pr-4">
                                            {Number.isFinite(r.meanHoverMs) ? r.meanHoverMs : '—'}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </details>
                ) : null}
            </div>
        </SceneContent>
    )
}

export const scene: SceneExport = {
    component: ChartBenchScene,
}
