import { Scope } from '../../scope'
import { EqualsPredicate, Pattern } from '../predicate'
import { LiteralExpr } from './literal'
import { RejectExpr } from './reject'

const whereType = (type: string): Pattern => new Pattern({ type: new EqualsPredicate(type) })

describe('RejectExpr', () => {
    const scope = Scope.forNode({}, 'user')
    const items = [
        { type: 'text', text: 'keep me' },
        { type: 'image', text: 'drop me' },
    ]

    it('drops elements matching where and keeps the rest', () => {
        const expr = new RejectExpr(new LiteralExpr(items), whereType('image'), null)
        expect(expr.eval(scope)).toEqual([items[0]])
    })

    it('returns the if_empty fallback when everything is rejected', () => {
        const allText = [{ type: 'text' }, { type: 'text' }]
        const expr = new RejectExpr(new LiteralExpr(allText), whereType('text'), new LiteralExpr('fallback'))
        expect(expr.eval(scope)).toBe('fallback')
    })

    it('a non-array source yields the empty/fallback result', () => {
        expect(new RejectExpr(new LiteralExpr('nope'), null, null).eval(scope)).toEqual([])
        expect(new RejectExpr(new LiteralExpr('nope'), null, new LiteralExpr('fallback')).eval(scope)).toBe('fallback')
    })
})
