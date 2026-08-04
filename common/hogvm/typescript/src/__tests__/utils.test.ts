import { toHogDate, toHogDateTime } from '../stl/date'
import { calculateCost, convertHogToJS, convertJSToHog, getNestedValue, unifyComparisonTypes } from '../utils'

const PTR_COST = 8

describe('hogvm utils', () => {
    describe('unifyComparisonTypes temporal ordering', () => {
        // Regression: `is date after`/`is date before` filters compile to `toDateTime(x) > toDateTime(y)`,
        // and the VM's GT opcode does `unifyComparisonTypes(a, b)` then `a > b`. Two HogDateTime objects
        // fell through unchanged, so `object > object` coerced to "[object Object]" and was always false —
        // realtime workflow date filters never matched. They must order by epoch seconds.
        const laterDateTime = toHogDateTime(1782988689) // 2026-06-28
        const earlierDateTime = toHogDateTime(1782518400) // 2026-06-23 00:00:00 UTC
        const laterDate = toHogDate(2026, 6, 28) // UTC midnight, exercises the isHogDate branch
        const earlierDate = toHogDate(2026, 6, 23)

        // Cover both temporalSeconds branches (HogDateTime → .dt, HogDate → toHogDateTime().dt) and the
        // cross-type pairings — the GT opcode does `unifyComparisonTypes(a, b)` then `a > b`.
        test.each([
            ['HogDateTime vs HogDateTime', laterDateTime, earlierDateTime],
            ['HogDate vs HogDate', laterDate, earlierDate],
            ['HogDate vs HogDateTime', laterDate, earlierDateTime],
            ['HogDateTime vs HogDate', laterDateTime, earlierDate],
        ])('orders %s chronologically', (_label, later, earlier) => {
            const [a, b] = unifyComparisonTypes(later, earlier)
            expect(a > b).toBe(true)
            expect(a < b).toBe(false)
        })

        test('equal instants compare equal', () => {
            const [a, b] = unifyComparisonTypes(laterDateTime, toHogDateTime(1782988689))
            expect(a === b).toBe(true)
        })

        // The same defect one step out: `event.timestamp` in filter globals is an ISO *string*, so a filter
        // like `timestamp > toDateTime('2026-07-01')` pairs a string with a HogDateTime. That pair fell
        // through unchanged too, and the string was compared against "[object Object]" — always false
        // whichever way the dates actually ordered.
        describe('datetime-shaped string against a temporal', () => {
            const cutoff = toHogDateTime(1782518400) // 2026-06-23 00:00:00 UTC

            test.each([
                ['offset-bearing ISO after the cutoff', '2026-06-28T12:00:00.000Z', true],
                ['offset-bearing ISO before the cutoff', '2026-06-01T12:00:00.000Z', false],
                // No offset: parsed as UTC, matching toDateTime() and ClickHouse's stored timestamps.
                ['naive ISO after the cutoff', '2026-06-28T12:00:00', true],
                ['naive ISO before the cutoff', '2026-06-01T12:00:00', false],
                ['date-only after the cutoff', '2026-06-28', true],
            ])('orders %s', (_label, timestamp, expected) => {
                const [a, b] = unifyComparisonTypes(timestamp, cutoff)
                expect(a > b).toBe(expected)
            })

            test('orders with the temporal on the left too', () => {
                const [a, b] = unifyComparisonTypes(cutoff, '2026-06-01T12:00:00.000Z')
                expect(a > b).toBe(true)
            })

            test('leaves a non-datetime string alone rather than coercing it to NaN', () => {
                const [a, b] = unifyComparisonTypes('not a date', cutoff)
                expect(a).toBe('not a date')
                expect(b).toBe(cutoff)
            })

            test('leaves string-to-string comparisons untouched', () => {
                // The coercion must only engage when the other side is temporal, or ordinary string filters
                // would start being read as dates.
                const [a, b] = unifyComparisonTypes('2026-06-28', '2026-06-01')
                expect(a).toBe('2026-06-28')
                expect(b).toBe('2026-06-01')
            })
        })
    })

    test('calculateCost', async () => {
        expect(calculateCost(1)).toBe(PTR_COST)
        expect(calculateCost('hello')).toBe(PTR_COST + 5)
        expect(calculateCost(true)).toBe(PTR_COST)
        expect(calculateCost(null)).toBe(PTR_COST)
        expect(calculateCost([])).toBe(PTR_COST)
        expect(calculateCost([1])).toBe(PTR_COST * 2)
        expect(calculateCost(['hello'])).toBe(PTR_COST * 2 + 5)
        expect(calculateCost({})).toBe(PTR_COST)
        expect(calculateCost({ key: 'value' })).toBe(PTR_COST * 3 + 3 + 5)
        expect(calculateCost(new Map([['key', 'value']]))).toBe(PTR_COST * 3 + 3 + 5)
        expect(
            calculateCost(
                new Map<any, any>([
                    ['key', 'value'],
                    ['key2', new Map<any, any>([['key', 'value']])],
                ])
            )
        ).toBe(PTR_COST * 7 + 3 + 5 + 4 + 3 + 5)
    })

    test('calculateCost with cycles', async () => {
        const obj: Record<string, any> = {}
        obj['key'] = obj
        expect(calculateCost(obj)).toBe(PTR_COST * 3 + 3)
    })

    test('convertJSToHog preserves circular references', () => {
        const obj: any = { a: null, b: true }
        obj.a = obj
        const hog = convertJSToHog(obj)
        expect(hog.get('a') === hog).toBe(true)
    })

    test('convertHogToJs preserves circular references', () => {
        const obj: any = { a: null, b: true }
        obj.a = obj
        const js = convertHogToJS(obj)
        expect(js.a === js).toBe(true)

        const map: any = new Map([
            ['a', null],
            ['b', true],
        ])
        map.set('a', map)
        const js2 = convertHogToJS(map)
        expect(js2.a === js2).toBe(true)
    })

    describe('getNestedValue', () => {
        test.each([
            ['own string key on plain object', { a: 1 }, ['a'], 1],
            ['missing key on plain object', { a: 1 }, ['b'], null],
            ['nested own keys on plain object', { a: { b: 2 } }, ['a', 'b'], 2],
            ['inherited toString returns null', {}, ['toString'], null],
            ['inherited hasOwnProperty returns null', {}, ['hasOwnProperty'], null],
            ['inherited constructor returns null', {}, ['constructor'], null],
            ['__proto__ does not traverse the chain', {}, ['__proto__'], null],
            ['Map key lookup', new Map([['a', 1]]), ['a'], 1],
            ['array index 1 returns first element', ['x', 'y'], [1], 'x'],
            ['array index -1 returns last element', ['x', 'y'], [-1], 'y'],
        ])('%s', (_label, obj, chain, expected) => {
            expect(getNestedValue(obj, chain)).toEqual(expected)
        })

        test('throws on zero-index array access', () => {
            expect(() => getNestedValue([1, 2], [0])).toThrow('Hog arrays start from index 1')
        })

        test('does not return inherited values from an array prototype', () => {
            expect(getNestedValue([], ['push'])).toBeNull()
            expect(getNestedValue([], ['map'])).toBeNull()
        })
    })
})
