import { Scope } from '../../scope'
import { LiteralExpr } from './literal'
import { StringifyExpr } from './stringify'

describe('StringifyExpr', () => {
    const scope = Scope.forNode({}, 'user')
    const stringify = (value: unknown): unknown => new StringifyExpr(new LiteralExpr(value)).eval(scope)

    it('JSON-encodes an object', () => {
        expect(stringify({ a: 1, b: 'two' })).toBe('{"a":1,"b":"two"}')
    })

    it.each([['plain'], [null], [undefined], [['a', 'b'] as unknown]])(
        'passes the content-slot value %p through untouched',
        (value) => {
            expect(stringify(value)).toEqual(value)
        }
    )

    it('falls back to String() when the value cannot be JSON-encoded', () => {
        const circular: Record<string, unknown> = {}
        circular.self = circular
        expect(stringify(circular)).toBe('[object Object]')
    })
})
