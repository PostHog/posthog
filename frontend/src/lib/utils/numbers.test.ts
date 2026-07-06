import {
    average,
    compactNumber,
    formatPercentageDiff,
    humanFriendlyLargeNumber,
    median,
    roundToDecimal,
} from 'lib/utils/numbers'

describe('numbers utils', () => {
    describe('compactNumber()', () => {
        it('formats number correctly', () => {
            expect(compactNumber(10)).toEqual('10')
            expect(compactNumber(293)).toEqual('293')
            expect(compactNumber(5001)).toEqual('5 K')
            expect(compactNumber(5312)).toEqual('5.31 K')
            expect(compactNumber(5392)).toEqual('5.39 K')
            expect(compactNumber(2833102)).toEqual('2.83 M')
            expect(compactNumber(8283310234)).toEqual('8.28 B')
            expect(compactNumber(null)).toEqual('-')
        })
    })

    describe('roundToDecimal()', () => {
        it('formats number correctly', () => {
            expect(roundToDecimal(null)).toEqual('-')
            expect(roundToDecimal(293)).toEqual('293.00')
            expect(roundToDecimal(102.121233)).toEqual('102.12')
            expect(roundToDecimal(102.99999)).toEqual('103.00')
            expect(roundToDecimal(1212)).toEqual('1212.00')
            expect(roundToDecimal(1212, 3)).toEqual('1212.000')
        })
    })

    describe('average()', () => {
        it('calculates average correctly', () => {
            expect(average([9, 4, 1, 3, 5, 7])).toEqual(4.8)
            expect(average([72, 35, 68, 66, 70, 9, 81])).toEqual(57.3) // Tests rounding too
            expect(average([86.4, 46.321, 45.304, 34.1, 147])).toEqual(71.8) // Tests rounding too
        })
    })

    describe('median()', () => {
        it('returns middle number if array length is odd', () => {
            expect(median([9, 4, 1, 3, 5, 7, 3, 6, 14])).toEqual(5)
        })
        it('returns avg of middle numbers if array length is even', () => {
            expect(median([9, 4, 0, 5, 7, 3, 6, 14])).toEqual(5.5)
        })
    })

    describe('humanFriendlyLargeNumber()', () => {
        it('returns the correct string', () => {
            expect(humanFriendlyLargeNumber(1.234)).toEqual('1.23')
            expect(humanFriendlyLargeNumber(12.34)).toEqual('12.3')
            expect(humanFriendlyLargeNumber(123.4)).toEqual('123')
            expect(humanFriendlyLargeNumber(1234)).toEqual('1.23K')
            expect(humanFriendlyLargeNumber(12345)).toEqual('12.3K')
            expect(humanFriendlyLargeNumber(123456)).toEqual('123K')
            expect(humanFriendlyLargeNumber(1234567)).toEqual('1.23M')
            expect(humanFriendlyLargeNumber(-1234567)).toEqual('-1.23M')
            expect(humanFriendlyLargeNumber(-1)).toEqual('-1')
            expect(humanFriendlyLargeNumber(-0.1)).toEqual('-0.1')
            expect(humanFriendlyLargeNumber(0)).toEqual('0')
            expect(humanFriendlyLargeNumber(NaN)).toEqual('NaN')
            expect(humanFriendlyLargeNumber(Infinity)).toEqual('inf')
            expect(humanFriendlyLargeNumber(-Infinity)).toEqual('-inf')
        })
    })

    describe('formatPercentageDiff()', () => {
        it.each([
            { current: 150, previous: 100, expected: '(+50.0%)' },
            { current: 200, previous: 100, expected: '(+100.0%)' },
            { current: 100, previous: 100, expected: '(+0.0%)' },
            { current: 50, previous: 100, expected: '(-50.0%)' },
            { current: 0, previous: 100, expected: '(-100.0%)' },
            { current: 125, previous: 100, expected: '(+25.0%)' },
            { current: 75, previous: 100, expected: '(-25.0%)' },
        ])('formats $current vs $previous as $expected', ({ current, previous, expected }) => {
            expect(formatPercentageDiff(current, previous)).toEqual(expected)
        })

        it.each([
            { current: 100, previous: 0, description: 'division by zero' },
            { current: 0, previous: 0, description: 'zero divided by zero' },
        ])('returns null for $description', ({ current, previous }) => {
            expect(formatPercentageDiff(current, previous)).toBeNull()
        })
    })
})
