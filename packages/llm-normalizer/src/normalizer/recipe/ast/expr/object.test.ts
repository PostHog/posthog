import { Scope } from '../../scope'
import { LiteralExpr } from './literal'
import { ObjectExpr } from './object'
import { PathExpr } from './path'

describe('ObjectExpr', () => {
    it('evaluates each field into an object', () => {
        const scope = Scope.forNode({ name: 'Ada' }, 'user')
        const expr = new ObjectExpr({ kind: new LiteralExpr('person'), label: new PathExpr(['name']) })
        expect(expr.eval(scope)).toEqual({ kind: 'person', label: 'Ada' })
    })

    it('empty spec yields an empty object', () => {
        expect(new ObjectExpr({}).eval(Scope.forNode({}, 'user'))).toEqual({})
    })
})
