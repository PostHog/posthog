import { Scope } from '../../scope'
import { JoinExpr } from './join'
import { LiteralExpr } from './literal'

describe('JoinExpr', () => {
    const scope = Scope.forNode({}, 'user')

    it('joins elements with the given separator', () => {
        const expr = new JoinExpr(new LiteralExpr(['a', 'b', 'c']), new LiteralExpr(', '), null)
        expect(expr.eval(scope)).toBe('a, b, c')
    })

    it('plucks a field from each object element when field is set', () => {
        const items = [{ text: 'one' }, { text: 'two' }]
        const expr = new JoinExpr(new LiteralExpr(items), new LiteralExpr(' / '), new LiteralExpr('text'))
        expect(expr.eval(scope)).toBe('one / two')
    })

    it('returns an empty string for a non-array source', () => {
        const expr = new JoinExpr(new LiteralExpr('not an array'), new LiteralExpr(', '), null)
        expect(expr.eval(scope)).toBe('')
    })
})
