import { Scope } from '../../scope'
import { PathExpr } from './path'

describe('PathExpr', () => {
    it('reads a nested field by path', () => {
        const scope = Scope.forNode({ message: { content: 'hello' } }, 'user')
        expect(new PathExpr(['message', 'content']).eval(scope)).toBe('hello')
    })

    it('returns undefined when the path is missing', () => {
        const scope = Scope.forNode({ message: {} }, 'user')
        expect(new PathExpr(['message', 'content']).eval(scope)).toBeUndefined()
        expect(new PathExpr(['missing', 'deep']).eval(scope)).toBeUndefined()
    })
})
