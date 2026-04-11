import { expect } from '@playwright/test'

import { test } from '../utils/playwright-test-base'

/**
 * Line-chart benchmark runner. Walks a matrix of {chart, series, points},
 * runs the in-scene benchmark harness at `/debug/chart-bench`, and prints a
 * comparison table to stdout + attaches it to the Playwright report.
 *
 * Skipped by default because benchmark numbers are noisy and we don't want
 * CI to fail on them. Run locally with:
 *
 *   hogli test playwright/e2e/chart-bench.spec.ts
 *
 * Or set CHART_BENCH=1 in the environment to opt in.
 */

type ChartKind = 'hog' | 'chartjs' | 'adapter-hog' | 'adapter-chartjs'

interface BenchResult {
    chart: ChartKind
    series: number
    points: number
    seed: number
    runs: number
    readyMs: number[]
    hoverMs: number[]
    meanReadyMs: number
    meanHoverMs: number
}

declare global {
    interface Window {
        __chartBench?: BenchResult
    }
}

const MATRIX: { series: number; points: number }[] = [
    // Realistic sizes first — these dominate real product usage.
    { series: 2, points: 30 }, // tiny tile
    { series: 5, points: 90 }, // typical trend
    { series: 20, points: 180 }, // 6mo daily breakdown
    { series: 50, points: 365 }, // 1yr daily breakdown
    // Stress sizes — upper bound, unlikely in product but useful as a ceiling.
    { series: 50, points: 2000 },
]

const CHARTS: ChartKind[] = ['hog', 'chartjs', 'adapter-hog', 'adapter-chartjs']
const RUNS = 5
const SEED = 42

const shouldRun = process.env.CHART_BENCH === '1'

// Register tests under `describe` when opted in, `describe.skip` otherwise.
// `test.skip()` inside the describe body throws at registration time and
// swallows the for-loop below, which is why we branch on the describe helper.
const describeBench = shouldRun ? test.describe : test.describe.skip

describeBench('Chart bench', () => {
    // One test per matrix cell so failures are scoped and the report is readable.
    for (const cell of MATRIX) {
        for (const chart of CHARTS) {
            test(`${chart} — ${cell.series} series × ${cell.points} points`, async ({ page }) => {
                const url = `/debug/chart-bench?chart=${chart}&series=${cell.series}&points=${cell.points}&runs=${RUNS}&seed=${SEED}`
                await page.goto(url)

                // Wait for the stage to mount before we click run, so the initial
                // mount isn't counted in the first measured run.
                await page.waitForSelector('[data-attr="chart-bench-stage"] canvas')

                await page.click('[data-attr="chart-bench-run"]')
                // The harness exposes the result on window when the run finishes.
                await page.waitForFunction(
                    (expectedRuns) => {
                        const result = window.__chartBench
                        return !!result && result.readyMs.length === expectedRuns
                    },
                    RUNS,
                    { timeout: 60_000 }
                )

                const result = await page.evaluate(() => window.__chartBench)
                expect(result).toBeTruthy()
                const r = result!

                // Attach the raw samples so they show up in the Playwright report.
                await test.info().attach(`${chart}-${cell.series}x${cell.points}.json`, {
                    body: JSON.stringify(r, null, 2),
                    contentType: 'application/json',
                })

                // eslint-disable-next-line no-console
                console.info(
                    `[chart-bench] ${chart.padEnd(8)} ${String(cell.series).padStart(3)}s × ${String(cell.points).padStart(4)}p  ` +
                        `ready=${r.meanReadyMs.toFixed(2)}ms  hover=${r.meanHoverMs.toFixed(2)}ms`
                )
            })
        }
    }
})
