import { Scope } from '../../scope'
import { SelfExpr } from './self'

describe('SelfExpr', () => {
    it('returns the whole input', () => {
        const input = { role: 'user', content: 'hi' }
        expect(new SelfExpr().eval(Scope.forNode(input, 'user'))).toBe(input)
    })

    it.each([['a string'], [42], [undefined]])('returns the primitive input %p as-is', (input) => {
        expect(new SelfExpr().eval(Scope.forNode(input, 'user'))).toBe(input)
    })
})
