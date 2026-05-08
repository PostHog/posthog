import { ciRanges, linearRegression, movingAverage, trendLine } from './statistics'

describe('linearRegression', () => {
    it('fits a perfect line through y = 2x + 1', () => {
        const result = linearRegression([
            [0, 1],
            [1, 3],
            [2, 5],
            [3, 7],
        ])
        expect(result.m).toBeCloseTo(2)
        expect(result.b).toBeCloseTo(1)
    })

    it('fits a flat line through constant y', () => {
        const result = linearRegression([
            [0, 5],
            [1, 5],
            [2, 5],
        ])
        expect(result.m).toBeCloseTo(0)
        expect(result.b).toBeCloseTo(5)
    })
})

describe('trendLine', () => {
    it('returns the input when fewer than 2 points', () => {
        expect(trendLine([])).toEqual([])
        expect(trendLine([5])).toEqual([5])
    })

    it('produces a perfect linear fit when input is already linear', () => {
        const result = trendLine([1, 3, 5, 7])
        expect(result).toEqual([1, 3, 5, 7])
    })

    it('produces a least-squares fit for noisy input', () => {
        const result = trendLine([0, 2, 1, 3, 4])
        expect(result.length).toBe(5)
        // monotonically increasing for upward trend
        for (let i = 1; i < result.length; i++) {
            expect(result[i]).toBeGreaterThanOrEqual(result[i - 1])
        }
    })

    describe('fitUpTo', () => {
        it('fits the regression to a prefix and extrapolates to the full length', () => {
            // First 3 points are y = x; tail is noisy. fitUpTo=3 → trend continues as y=x.
            const result = trendLine([0, 1, 2, 100, 200], 3)
            expect(result).toHaveLength(5)
            expect(result[0]).toBeCloseTo(0)
            expect(result[1]).toBeCloseTo(1)
            expect(result[2]).toBeCloseTo(2)
            expect(result[3]).toBeCloseTo(3)
            expect(result[4]).toBeCloseTo(4)
        })

        it('clamps fitUpTo to a minimum of 2', () => {
            // With fitUpTo=1 (clamped to 2), uses only the first 2 points → y = x.
            const result = trendLine([0, 1, 100, 200, 300], 1)
            expect(result[0]).toBeCloseTo(0)
            expect(result[1]).toBeCloseTo(1)
            expect(result[2]).toBeCloseTo(2)
        })

        it('clamps fitUpTo to the input length', () => {
            const result = trendLine([1, 3, 5], 999)
            expect(result).toEqual([1, 3, 5])
        })
    })
})

describe('movingAverage', () => {
    it('returns the input when fewer points than the window', () => {
        expect(movingAverage([1, 2, 3], 7)).toEqual([1, 2, 3])
    })

    it('smooths uniform input to itself', () => {
        const result = movingAverage([5, 5, 5, 5, 5, 5, 5, 5], 3)
        expect(result).toEqual([5, 5, 5, 5, 5, 5, 5, 5])
    })

    it('smooths a step change with a window-3 average', () => {
        const result = movingAverage([0, 0, 0, 3, 3, 3, 3, 3], 3)
        expect(result).toHaveLength(8)
        expect(result[0]).toBeCloseTo(0)
        expect(result[7]).toBeCloseTo(3)
        // middle values are between 0 and 3
        expect(result[3]).toBeGreaterThan(0)
        expect(result[3]).toBeLessThan(3)
    })

    it('defaults to a window of 7', () => {
        const result = movingAverage([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        const explicit = movingAverage([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 7)
        expect(result).toEqual(explicit)
    })
})

describe('ciRanges', () => {
    it('returns the input as both bounds when fewer than 2 values', () => {
        expect(ciRanges([])).toEqual([[], []])
        expect(ciRanges([5])).toEqual([[5], [5]])
    })

    it('produces lower ≤ value ≤ upper for each point', () => {
        const values = [10, 12, 8, 14, 9, 11, 13]
        const [lower, upper] = ciRanges(values)
        expect(lower).toHaveLength(values.length)
        expect(upper).toHaveLength(values.length)
        for (let i = 0; i < values.length; i++) {
            expect(lower[i]).toBeLessThanOrEqual(values[i])
            expect(upper[i]).toBeGreaterThanOrEqual(values[i])
        }
    })

    it('produces a symmetric band around each value', () => {
        const values = [10, 20, 30]
        const [lower, upper] = ciRanges(values)
        for (let i = 0; i < values.length; i++) {
            const halfBand = upper[i] - values[i]
            expect(values[i] - lower[i]).toBeCloseTo(halfBand)
        }
    })

    it('produces zero band for constant values', () => {
        const [lower, upper] = ciRanges([5, 5, 5, 5])
        expect(lower).toEqual([5, 5, 5, 5])
        expect(upper).toEqual([5, 5, 5, 5])
    })

    it('widens with lower confidence (e.g. 0.99 vs 0.5)', () => {
        const values = [10, 12, 8, 14, 9, 11, 13]
        const narrow = ciRanges(values, 0.5)
        const wide = ciRanges(values, 0.99)
        expect(wide[1][0] - wide[0][0]).toBeGreaterThan(narrow[1][0] - narrow[0][0])
    })
})
