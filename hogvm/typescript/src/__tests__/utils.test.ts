import { calculateCost } from '../utils'

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
})
