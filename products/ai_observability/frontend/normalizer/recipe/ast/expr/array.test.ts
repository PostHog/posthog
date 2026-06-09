import { Scope } from '../../scope'
import { ArrayExpr } from './array'
import { LiteralExpr } from './literal'
import { PathExpr } from './path'

describe('ArrayExpr', () => {
    it('evaluates each element against the scope', () => {
        const scope = Scope.forNode({ name: 'Ada' }, 'user')
        const expr = new ArrayExpr([new LiteralExpr('greeting'), new PathExpr(['name'])])
        expect(expr.eval(scope)).toEqual(['greeting', 'Ada'])
    })

    it('empty spec yields an empty array', () => {
        expect(new ArrayExpr([]).eval(Scope.forNode({}, 'user'))).toEqual([])
    })
})
