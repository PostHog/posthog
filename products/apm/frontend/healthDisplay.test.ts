import { compareNullable, formatRateIn, tableRateUnit } from './healthDisplay'

describe('healthDisplay', () => {
    // Mixing "/s" and "/min" in one column made 0.1/min read as busier than 0.2/s.
    test.each([
        { rates: [0.004, 0.05, null], expected: 'req/min' },
        { rates: [0.004, 0.1], expected: 'req/s' },
        { rates: [null], expected: 'req/min' },
    ])('picks $expected for $rates', ({ rates, expected }) => {
        expect(tableRateUnit(rates)).toBe(expected)
    })

    test.each([
        { perSecond: 1234, unit: 'req/s' as const, expected: '1.2k' },
        { perSecond: 0.25, unit: 'req/s' as const, expected: '0.3' },
        { perSecond: 0.004, unit: 'req/s' as const, expected: '<0.01' },
        { perSecond: 0.05, unit: 'req/min' as const, expected: '3.0' },
        { perSecond: 0, unit: 'req/min' as const, expected: '0' },
        { perSecond: null, unit: 'req/s' as const, expected: '—' },
    ])('formats $perSecond in $unit as $expected', ({ perSecond, unit, expected }) => {
        expect(formatRateIn(perSecond, unit)).toBe(expected)
    })

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
