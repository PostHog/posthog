import { Scope } from '../../scope'
import { EqualsPredicate, Pattern } from '../predicate'
import { LiteralExpr } from './literal'
import { PathExpr } from './path'
import { SelectExpr } from './select'

const whereType = (type: string): Pattern => new Pattern({ type: new EqualsPredicate(type) })

describe('SelectExpr', () => {
    const scope = Scope.forNode({}, 'user')
    const items = [
        { type: 'text', text: 'keep me' },
        { type: 'image', text: 'drop me' },
        { type: 'text', text: 'keep me too' },
    ]

    it('keeps elements matching where', () => {
        const expr = new SelectExpr(new LiteralExpr(items), whereType('text'), null, null)
        expect(expr.eval(scope)).toEqual([items[0], items[2]])
    })

    it('plucks a value from each kept element', () => {
        const expr = new SelectExpr(new LiteralExpr(items), whereType('text'), new PathExpr(['text']), null)
        expect(expr.eval(scope)).toEqual(['keep me', 'keep me too'])
    })

    it('returns the if_empty fallback when nothing matches', () => {
        const expr = new SelectExpr(new LiteralExpr(items), whereType('audio'), null, new LiteralExpr('fallback'))
        expect(expr.eval(scope)).toBe('fallback')
    })

    it('a non-array source yields the empty/fallback result', () => {
        expect(new SelectExpr(new LiteralExpr('nope'), null, null, null).eval(scope)).toEqual([])
        expect(new SelectExpr(new LiteralExpr('nope'), null, null, new LiteralExpr('fallback')).eval(scope)).toBe(
            'fallback'
        )
    })
})
