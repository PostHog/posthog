import { standardDeviation, probit, linearRegression } from 'simple-statistics'

/**
 * Calculates the confidence interval ranges for a given set of values.
 *
 * @param values - An array of numbers for which to calculate the confidence interval.
 * @param ci - The confidence interval, as a number between 0 and 1. Defaults to 0.95.
 * @returns A tuple containing two arrays: the lower and upper bounds of the confidence interval.
 */
export function ciRanges(values: number[], ci: number = 0.95): [number[], number[]] {
    const n = values.length
    if (n < 2) {
        return [values, values]
    }

    const sd = standardDeviation(values)
    const se = sd / Math.sqrt(n)
    // The probit function is the inverse of the standard normal CDF.
    // It's used here to calculate the z-score for the given confidence interval.
    const z = probit((1 + ci) / 2)
    const h = z * se

    const upper = values.map((v) => v + h)
    const lower = values.map((v) => v - h)
    return [lower, upper]
}

export function trendLine(values: number[]): number[] {
    const n = values.length
    if (n < 2) {
        return values
    }

    const coordinates: [number, number][] = values.map((y, x) => [x, y])
    const { m, b } = linearRegression(coordinates)

    return values.map((_, x) => m * x + b)
}
