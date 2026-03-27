import { buildPointClickData, findNearestIndex, linearRegression } from '../core/interaction'
import type { Series } from '../core/types'

describe('hog-charts interaction', () => {
    const makeSeries = (data: number[], key = 'test'): Series => ({
        key,
        label: key,
        data,
        color: '#1d4aff',
    })

    describe('findNearestIndex', () => {
        const labels = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
        const xScale = (label: string): number | undefined => {
            const positions: Record<string, number> = {
                Mon: 50,
                Tue: 200,
                Wed: 350,
                Thu: 500,
                Fri: 650,
            }
            return positions[label]
        }

        it('finds exact match', () => {
            expect(findNearestIndex(200, labels, xScale)).toBe(1)
        })

        it('finds nearest when between points', () => {
            // 260 is closer to Tue (200) than Wed (350)
            expect(findNearestIndex(260, labels, xScale)).toBe(1)
            // 290 is closer to Wed (350) than Tue (200)
            expect(findNearestIndex(290, labels, xScale)).toBe(2)
        })

        it('returns first index for far left', () => {
            expect(findNearestIndex(0, labels, xScale)).toBe(0)
        })

        it('returns last index for far right', () => {
            expect(findNearestIndex(1000, labels, xScale)).toBe(4)
        })

        it('returns -1 for empty labels', () => {
            expect(findNearestIndex(100, [], xScale)).toBe(-1)
        })
    })

    describe('buildPointClickData', () => {
        it('builds click data with cross-series data', () => {
            const series = [makeSeries([10, 20, 30], 'signups'), makeSeries([5, 10, 15], 'activations')]
            const labels = ['Mon', 'Tue', 'Wed']

            const result = buildPointClickData(1, series, labels)
            expect(result).not.toBeNull()
            expect(result!.dataIndex).toBe(1)
            expect(result!.label).toBe('Tue')
            expect(result!.value).toBe(20)
            expect(result!.crossSeriesData).toHaveLength(2)
            expect(result!.crossSeriesData[0].value).toBe(20)
            expect(result!.crossSeriesData[1].value).toBe(10)
        })

        it('returns null for out-of-range index', () => {
            expect(buildPointClickData(-1, [makeSeries([1])], ['Mon'])).toBeNull()
            expect(buildPointClickData(5, [makeSeries([1])], ['Mon'])).toBeNull()
        })

        it('skips hidden series', () => {
            const series = [{ ...makeSeries([10, 20], 'hidden'), hidden: true }, makeSeries([5, 10], 'visible')]
            const result = buildPointClickData(0, series, ['Mon', 'Tue'])
            expect(result!.series.key).toBe('visible')
            expect(result!.crossSeriesData).toHaveLength(1)
        })
    })

    describe('linearRegression', () => {
        it('computes correct regression for perfect line', () => {
            // y = 2x + 1
            const data = [1, 3, 5, 7, 9]
            const result = linearRegression(data)

            expect(result).not.toBeNull()
            expect(result!.slope).toBeCloseTo(2, 5)
            expect(result!.intercept).toBeCloseTo(1, 5)
        })

        it('respects endIndex to exclude incomplete data', () => {
            const data = [1, 3, 5, 100, 200] // last two are "incomplete"
            const result = linearRegression(data, 3)

            expect(result).not.toBeNull()
            expect(result!.slope).toBeCloseTo(2, 5)
            expect(result!.intercept).toBeCloseTo(1, 5)
        })

        it('returns null for insufficient data', () => {
            expect(linearRegression([])).toBeNull()
            expect(linearRegression([5])).toBeNull()
        })

        it('handles constant data', () => {
            const result = linearRegression([5, 5, 5, 5])
            expect(result).not.toBeNull()
            expect(result!.slope).toBeCloseTo(0, 5)
            expect(result!.intercept).toBeCloseTo(5, 5)
        })
    })
})
