import { compareNullable } from './healthDisplay'

describe('compareNullable', () => {
    test.each([
        // JavaScript coerces null to 0 in subtraction, which would rank a missing p95 level with a 0ms one.
        { a: null, b: 0, expected: -1 },
        { a: 0, b: null, expected: 1 },
        { a: null, b: null, expected: 0 },
        { a: 2, b: 10, expected: -1 },
    ])('orders $a against $b', ({ a, b, expected }) => {
        expect(Math.sign(compareNullable(a, b))).toBe(expected)
    })
})
