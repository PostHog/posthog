import { sanitizeRetentionInterval } from './RetentionCondition'

describe('sanitizeRetentionInterval', () => {
    // A decimal used to reach totalIntervals unchanged, so the query failed and the saved
    // insight stayed broken. Each case locks in a whole number in range.
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
    ])('coerces %p to a whole number in range', (input, expected) => {
        expect(sanitizeRetentionInterval(input)).toEqual(expected)
    })
})
