import { stringifyWithBigInts, tryJsonParse, validateJson } from 'lib/utils/json'

describe('lib/utils/json', () => {
    describe('validateJson', () => {
        it.each([
            ['valid object', '{"a":1}', true],
            ['valid array', '[1,2,3]', true],
            ['invalid json', '{not json}', false],
            ['empty string', '', false],
        ])('returns %s as %s', (_label, input, expected) => {
            expect(validateJson(input)).toEqual(expected)
        })
    })

    describe('tryJsonParse', () => {
        it('parses valid json', () => {
            expect(tryJsonParse('{"a":1}')).toEqual({ a: 1 })
        })

        it('returns the fallback on invalid json', () => {
            expect(tryJsonParse('{not json}', 'fallback')).toEqual('fallback')
        })
    })

    describe('stringifyWithBigInts', () => {
        it.each([
            ['plain string', 'hello', '"hello"'],
            ['plain number', 42, '42'],
            ['null', null, 'null'],
            ['plain object', { a: 1, b: 'two' }, '{"a":1,"b":"two"}'],
            ['array of primitives', [1, 2, 3], '[1,2,3]'],
            ['top-level bigint', BigInt('9007199254740993'), '"9007199254740993"'],
            ['object with bigint', { id: BigInt('9007199254740993') }, '{"id":"9007199254740993"}'],
            ['array of bigints', [BigInt(1), BigInt(2)], '["1","2"]'],
            ['nested bigint', { a: { b: BigInt(7) } }, '{"a":{"b":"7"}}'],
            ['mixed types', { n: 1, b: BigInt(2), s: 'x', a: [BigInt(3)] }, '{"n":1,"b":"2","s":"x","a":["3"]}'],
        ])('serialises %s', (_label, input, expected) => {
            expect(stringifyWithBigInts(input)).toEqual(expected)
        })

        it('does not throw on a bigint where JSON.stringify would throw', () => {
            expect(() => stringifyWithBigInts(BigInt(1))).not.toThrow()
        })

        it('matches JSON.stringify for undefined', () => {
            expect(stringifyWithBigInts(undefined)).toBeUndefined()
            expect(stringifyWithBigInts({ a: undefined, b: 1 })).toEqual('{"b":1}')
        })
    })
})
