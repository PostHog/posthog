import { verifiedFilterFromOption, verifiedFilterValue } from './utils'

describe('data-management utils', () => {
    describe('verifiedFilterValue', () => {
        it.each([
            { input: undefined, expected: 'all' },
            { input: true, expected: 'verified' },
            { input: false, expected: 'unverified' },
        ])('returns "$expected" when verified is $input', ({ input, expected }) => {
            expect(verifiedFilterValue(input)).toBe(expected)
        })
    })

    describe('verifiedFilterFromOption', () => {
        it.each([
            { input: 'all' as const, expected: undefined },
            { input: 'verified' as const, expected: true },
            { input: 'unverified' as const, expected: false },
        ])('returns $expected when option is "$input"', ({ input, expected }) => {
            expect(verifiedFilterFromOption(input)).toBe(expected)
        })
    })

    describe('round-trip', () => {
        it.each([undefined, true, false])('verifiedFilterFromOption(verifiedFilterValue(%s)) === %s', (value) => {
            expect(verifiedFilterFromOption(verifiedFilterValue(value))).toBe(value)
        })
    })
})
