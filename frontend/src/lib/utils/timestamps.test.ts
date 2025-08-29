import { parseTimestampToMs } from './timestamps'

describe('parseTimestampToMs', () => {
    describe('valid inputs', () => {
        const validCases: Array<[string, number]> = [
            // mm:ss format
            ['00:30', 30000], // 30 seconds
            ['01:30', 90000], // 1 minute 30 seconds
            ['10:00', 600000], // 10 minutes
            ['59:59', 3599000], // 59 minutes 59 seconds

            // hh:mm:ss format
            ['01:01:30', 3690000], // 1 hour 1 minute 30 seconds
            ['02:00:00', 7200000], // 2 hours
            ['00:00:05', 5000], // 5 seconds
            ['23:59:59', 86399000], // 23 hours 59 minutes 59 seconds

            // Edge cases with valid times
            ['0:05', 5000], // Single digit minute
            ['1:2', 62000], // Single digit seconds (1:2 interpreted as 1 minute 2 seconds)
        ]

        validCases.forEach(([input, expected]) => {
            it(`should parse "${input}" to ${expected}ms`, () => {
                expect(parseTimestampToMs(input)).toBe(expected)
            })
        })
    })

    describe('invalid inputs', () => {
        const invalidCases = [
            '', // empty string
            '   ', // whitespace only
            'invalid', // non-numeric
            '1:2:3:4', // too many parts
            '1', // single number
            '-1:30', // negative values
            '1:-30', // negative seconds
            '1:2:3:4:5', // too many colons
            'abc:def', // non-numeric parts
        ]

        invalidCases.forEach((input) => {
            it(`should return undefined for "${input}"`, () => {
                expect(parseTimestampToMs(input)).toBeUndefined()
            })
        })
    })

    describe('null and undefined inputs', () => {
        it('should return undefined for null', () => {
            expect(parseTimestampToMs(null)).toBeUndefined()
        })

        it('should return undefined for undefined', () => {
            expect(parseTimestampToMs(undefined)).toBeUndefined()
        })

        it('should return undefined for empty string', () => {
            expect(parseTimestampToMs('')).toBeUndefined()
        })
    })

    describe('edge cases', () => {
        it('should handle zero values', () => {
            expect(parseTimestampToMs('00:00')).toBe(0) // 0 ms
        })

        it('should handle large values', () => {
            expect(parseTimestampToMs('99:99:99')).toBe(362439000) // let's allow minutes and seconds to be > 60, why not
        })

        it('should trim whitespace', () => {
            expect(parseTimestampToMs('  01:30  ')).toBe(90000)
        })
    })
})
