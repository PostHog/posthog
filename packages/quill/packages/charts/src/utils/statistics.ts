// Self-contained statistics helpers for hog-charts. Wraps `simple-statistics`
// directly so the library has no PostHog imports.

import { linearRegression as ssLinearRegression, probit, standardDeviation } from 'simple-statistics'

export function linearRegression(data: ReadonlyArray<readonly [number, number]>): { m: number; b: number } {
    return ssLinearRegression(data as [number, number][])
}

/** Symmetric confidence interval bounds for a sample of values, using the normal
 *  approximation (`±z·SE`). Returns `[lower, upper]` arrays, both the same length
 *  as the input. */
export function ciRanges(values: number[], ci: number = 0.95): [number[], number[]] {
    const n = values.length
    if (n < 2) {
        return [values, values]
    }
    const sd = standardDeviation(values)
    const se = sd / Math.sqrt(n)
    const z = probit((1 + ci) / 2)
    const h = z * se
    const upper = values.map((v) => v + h)
    const lower = values.map((v) => v - h)
    return [lower, upper]
}

export function trendLine(values: number[], fitUpTo?: number): number[] {
    const n = values.length
    if (n < 2) {
        return values
    }
    const fitEnd = fitUpTo != null ? Math.max(2, Math.min(fitUpTo, n)) : n
    const coordinates: [number, number][] = values.slice(0, fitEnd).map((y, x) => [x, y])
    const { m, b } = linearRegression(coordinates)
    return values.map((_, x) => m * x + b)
}

export function movingAverage(values: number[], intervals: number = 7): number[] {
    const n = values.length
    if (n < intervals) {
        return values
    }
    return values.map((_, index) => {
        const start = Math.max(0, index - Math.floor(intervals / 2))
        const end = Math.min(n, start + intervals)
        const actualStart = Math.max(0, end - intervals)
        const slice = values.slice(actualStart, end)
        return slice.reduce((sum, val) => sum + val, 0) / slice.length
    })
}
