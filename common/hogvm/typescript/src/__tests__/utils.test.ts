import { calculateCost, convertHogToJS, convertJSToHog, getNestedValue } from '../utils'

const PTR_COST = 8

describe('hogvm utils', () => {
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
