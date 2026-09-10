import { Scope } from '../../scope'
import { InterpExpr } from './interp'
import { PathExpr } from './path'

describe('InterpExpr', () => {
    it('splices evaluated values between literal text', () => {
        const scope = Scope.forNode({ name: 'Ada', lang: 'Hog' }, 'user')
        const expr = new InterpExpr([new PathExpr(['name']), ' writes ', new PathExpr(['lang'])])
        expect(expr.eval(scope)).toBe('Ada writes Hog')
    })

    it('a missing or null value renders as an empty string', () => {
        const scope = Scope.forNode({ name: null }, 'user')
        const expr = new InterpExpr(['name: ', new PathExpr(['name']), new PathExpr(['missing'])])
        expect(expr.eval(scope)).toBe('name: ')
    })
})
