import { Scope } from '../../scope'
import { LiteralExpr } from './literal'

describe('LiteralExpr', () => {
    const scope = Scope.forNode({ ignored: true }, 'user')

    it('returns the wrapped value', () => {
        expect(new LiteralExpr('hello').eval(scope)).toBe('hello')
        expect(new LiteralExpr({ a: 1 }).eval(scope)).toEqual({ a: 1 })
    })

    it.each([[0], [''], [false], [null]])('returns the falsy value %p unchanged', (value) => {
        expect(new LiteralExpr(value).eval(scope)).toBe(value)
    })
})
