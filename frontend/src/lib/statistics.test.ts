import { ciRanges, movingAverage, trendLine } from './statistics'

describe('statistics', () => {
    describe('ciRanges', () => {
        it('calculates confidence interval ranges correctly', () => {
            const values = [10, 12, 11, 13, 11.5]
            const [lower, upper] = ciRanges(values, 0.95)

            expect(lower.map((n) => n.toFixed(2))).toEqual(['9.12', '11.12', '10.12', '12.12', '10.62'])
            expect(upper.map((n) => n.toFixed(2))).toEqual(['10.88', '12.88', '11.88', '13.88', '12.38'])
        })

        it('handles fewer than 2 values', () => {
            const values = [10]
            const [lower, upper] = ciRanges(values)
            expect(lower).toEqual([10])
            expect(upper).toEqual([10])
        })

        it('handles different confidence intervals', () => {
            const values = [10, 12, 11, 13, 11.5]
            const [lower, upper] = ciRanges(values, 0.99)

            expect(lower.map((n) => n.toFixed(2))).toEqual(['8.85', '10.85', '9.85', '11.85', '10.35'])
            expect(upper.map((n) => n.toFixed(2))).toEqual(['11.15', '13.15', '12.15', '14.15', '12.65'])
        })
    })

    describe('trendLine', () => {
        it('calculates a linear trend line correctly', () => {
            const values = [1, 2, 3, 4, 5]
            const result = trendLine(values)
            expect(result.map((n) => n.toFixed(2))).toEqual(['1.00', '2.00', '3.00', '4.00', '5.00'])
        })

        it('calculates a more complex trend line', () => {
            const values = [1, 3, 2, 5, 4]
            const result = trendLine(values)
            expect(result.map((n) => n.toFixed(2))).toEqual(['1.40', '2.20', '3.00', '3.80', '4.60'])
        })

        it('handles fewer than 2 values', () => {
            const values = [10]
            const result = trendLine(values)
            expect(result).toEqual([10])
        })
    })

    describe('movingAverage', () => {
        it('calculates moving average correctly with default intervals', () => {
            const values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
            const result = movingAverage(values)
            expect(result.map((n) => n.toFixed(2))).toEqual([
                '4.00',
                '4.00',
                '4.00',
                '4.00',
                '5.00',
                '6.00',
                '7.00',
                '7.00',
                '7.00',
                '7.00',
            ])
        })

        it('calculates moving average with specified intervals', () => {
            const values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
            const result = movingAverage(values, 3)
            expect(result.map((n) => n.toFixed(2))).toEqual([
                '2.00',
                '2.00',
                '3.00',
                '4.00',
                '5.00',
                '6.00',
                '7.00',
                '8.00',
                '9.00',
                '9.00',
            ])
        })

        it('handles fewer values than intervals', () => {
            const values = [1, 2, 3]
            const result = movingAverage(values, 5)
            expect(result).toEqual([1, 2, 3])
        })
    })
})
