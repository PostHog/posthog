import { CompatMessage } from '../../../../types'
import { Scope } from '../../scope'
import { LiteralExpr } from '../expr'
import { Pattern } from '../predicate'
import { DelegateRule } from './delegate'
import { DispatchEngine, NO_MATCH } from './dispatch'

const scope = Scope.forNode({ role: 'assistant' }, 'user')

describe('DelegateRule', () => {
    it('re-dispatches the derived value and returns its messages', () => {
        const inner: CompatMessage[] = [{ role: 'assistant', content: 'delegated' }]
        const dispatch = jest.fn().mockReturnValue(inner)
        const engine: DispatchEngine = { dispatch, coercer: { buildMessage: jest.fn(), stamp: jest.fn() } }

        const rule = new DelegateRule(new Pattern({}), [], new LiteralExpr({ unwrapped: true }))
        expect(rule.produce(scope, engine, false, 3)).toBe(inner)
        // delegation re-dispatches the derived value at the next depth, carrying the resolved role
        expect(dispatch).toHaveBeenCalledWith({ unwrapped: true }, 'assistant', 4)
    })

    it('returns nothing when the delegated value matches no recipe', () => {
        const engine: DispatchEngine = {
            dispatch: jest.fn().mockReturnValue(NO_MATCH),
            coercer: { buildMessage: jest.fn(), stamp: jest.fn() },
        }
        const rule = new DelegateRule(new Pattern({}), [], new LiteralExpr('anything'))
        expect(rule.produce(scope, engine, false, 0)).toEqual([])
    })
})
