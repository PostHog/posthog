import { sanitizeCustomBracket, sanitizeRetentionInterval } from './RetentionCondition'

describe('RetentionCondition input sanitizers', () => {
    // A decimal used to reach totalIntervals unchanged, so the query failed and the saved
    // insight stayed broken. Each case locks in a whole number in range.
    describe('sanitizeRetentionInterval', () => {
        test.each([
            ['2', { value: 2, exceededMax: false }],
            ['2.5', { value: 3, exceededMax: false }],
            ['2.4', { value: 2, exceededMax: false }],
            ['31', { value: 31, exceededMax: false }],
            ['0', { value: 1, exceededMax: false }],
            ['-3', { value: 1, exceededMax: false }],
            ['', { value: 1, exceededMax: false }],
            ['abc', { value: 1, exceededMax: false }],
            ['40', { value: 10, exceededMax: true }],
            ['25000', { value: 25, exceededMax: true }],
            ['99999', { value: 10, exceededMax: true }],
            ['00032', { value: 10, exceededMax: true }],
        ])('coerces %p to a whole number in range', (input, expected) => {
            expect(sanitizeRetentionInterval(input)).toEqual(expected)
        })
    })

    // A rounded value below 1 (e.g. 0.4 rounds to 0) or a non-finite value from a cleared field
    // is dropped by the retention listener, which silently removes the bracket. Each case locks
    // in either a value of at least 1 or an explicit empty (undefined) that keeps the row.
    describe('sanitizeCustomBracket', () => {
        test.each([
            [2, 2],
            [3.6, 4],
            [0.4, 1],
            [0, 1],
            [-3, 1],
            [undefined, undefined],
            [NaN, undefined],
        ])('coerces %p to %p', (input, expected) => {
            expect(sanitizeCustomBracket(input)).toEqual(expected)
        })
    })
})
