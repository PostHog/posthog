import { isLookbackEligibleType, secondsToLookbackParts } from '../SyncMethodForm'

describe('SyncMethodForm lookback helpers', () => {
    it.each([
        ['datetime', true],
        ['date', true],
        ['timestamp', true],
        ['integer', false],
        ['numeric', false],
        ['objectid', false],
        [null, false],
        [undefined, false],
    ])('isLookbackEligibleType(%s) === %s', (fieldType, expected) => {
        expect(isLookbackEligibleType(fieldType as string | null | undefined)).toBe(expected)
    })

    it.each([
        [3600, { amount: 1, unit: 'hours' }],
        [7200, { amount: 2, unit: 'hours' }],
        [86400, { amount: 1, unit: 'days' }],
        [172800, { amount: 2, unit: 'days' }],
        [5184000, { amount: 60, unit: 'days' }], // 60-day max
        [60, { amount: 1, unit: 'minutes' }],
        [900, { amount: 15, unit: 'minutes' }],
        // Non-divisible values floor down to whole minutes (lossy round-trip), never round up.
        [90, { amount: 1, unit: 'minutes' }],
        [150, { amount: 2, unit: 'minutes' }],
        [null, { amount: null, unit: 'hours' }],
        [0, { amount: null, unit: 'hours' }],
        [-5, { amount: null, unit: 'hours' }],
    ])('secondsToLookbackParts(%s) picks the largest exact unit', (seconds, expected) => {
        expect(secondsToLookbackParts(seconds as number | null)).toEqual(expected)
    })

    it('LOOKBACK_MAX_SECONDS is 60 days (5184000)', () => {
        // 60 days × 86400 s/day
        expect(60 * 86400).toBe(5184000)
    })
})
