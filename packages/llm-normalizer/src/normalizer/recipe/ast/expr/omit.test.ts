import { Scope } from '../../scope'
import { LiteralExpr } from './literal'
import { OmitExpr } from './omit'

describe('OmitExpr', () => {
    const scope = Scope.forNode({}, 'user')

    it('returns a copy without the listed keys', () => {
        const expr = new OmitExpr(new LiteralExpr({ a: 1, b: 2, c: 3 }), new LiteralExpr(['b']))
        expect(expr.eval(scope)).toEqual({ a: 1, c: 3 })
    })

    it('does not mutate the source object', () => {
        const source = { a: 1, b: 2 }
        new OmitExpr(new LiteralExpr(source), new LiteralExpr(['b'])).eval(scope)
        expect(source).toEqual({ a: 1, b: 2 })
    })

    it('returns an empty object for a non-object source', () => {
        expect(new OmitExpr(new LiteralExpr('nope'), new LiteralExpr(['b'])).eval(scope)).toEqual({})
        expect(new OmitExpr(new LiteralExpr([1, 2]), new LiteralExpr(['b'])).eval(scope)).toEqual({})
    })
})
