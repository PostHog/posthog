import { recordingsDateFromForLastSeen, verifiedFilterFromOption, verifiedFilterValue } from './utils'

describe('data-management utils', () => {
    describe('recordingsDateFromForLastSeen', () => {
        beforeEach(() => {
            jest.useFakeTimers().setSystemTime(new Date('2026-07-31T12:00:00Z'))
        })

        afterEach(() => {
            jest.useRealTimers()
        })

        it.each([
            { lastSeenAt: undefined, expected: '-3d', reason: 'no last_seen_at falls back to the default window' },
            {
                lastSeenAt: '2026-07-30T12:00:00Z',
                expected: '-3d',
                reason: 'recently seen events keep the default window',
            },
            {
                lastSeenAt: '2026-07-01T12:00:00Z',
                expected: '-31d',
                reason: 'a stale event widens the window to cover its last occurrence',
            },
        ])('$reason', ({ lastSeenAt, expected }) => {
            expect(recordingsDateFromForLastSeen(lastSeenAt)).toBe(expected)
        })
    })
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
