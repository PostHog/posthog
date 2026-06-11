import { Scope } from '../../scope'
import { Expr } from './base'
import { LiteralExpr } from './literal'

describe('LiteralExpr', () => {
    const scope = Scope.forNode({ ignored: true }, 'user')

    // Through the Expr interface: LiteralExpr narrows eval() to take no scope,
    // but the point is that it ignores whatever scope a caller passes.
    const evalLiteral = (value: unknown): unknown => {
        const expr: Expr = new LiteralExpr(value)
        return expr.eval(scope)
    }

    it('returns the wrapped value', () => {
        expect(evalLiteral('hello')).toBe('hello')
        expect(evalLiteral({ a: 1 })).toEqual({ a: 1 })
    })

    it.each([[0], [''], [false], [null]])('returns the falsy value %p unchanged', (value) => {
        expect(evalLiteral(value)).toBe(value)
    })
})
