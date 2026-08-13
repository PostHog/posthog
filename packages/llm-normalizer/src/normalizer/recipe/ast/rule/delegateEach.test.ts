import { CompatMessage } from '../../../../types'
import { Scope } from '../../scope'
import { LiteralExpr } from '../expr'
import { Pattern } from '../predicate'
import { DelegateEachRule } from './delegateEach'
import { DispatchEngine, NO_MATCH } from './dispatch'

const scope = Scope.forNode({ role: 'user' }, 'user')

describe('DelegateEachRule', () => {
    it('dispatches each element and concatenates the messages', () => {
        const dispatch = jest
            .fn()
            .mockReturnValueOnce([{ role: 'user', content: 'a' }])
            .mockReturnValueOnce([{ role: 'user', content: 'b' }])
        const engine: DispatchEngine = { dispatch, coercer: { buildMessage: jest.fn(), stamp: jest.fn() } }

        const rule = new DelegateEachRule(new Pattern({}), [], new LiteralExpr(['x', 'y']), null)
        expect(rule.produce(scope, engine, false, 0)).toEqual([
            { role: 'user', content: 'a' },
            { role: 'user', content: 'b' },
        ])
    })

    it('stamps the parent context onto produced messages when stamp is set', () => {
        const stamp = jest.fn((msg: CompatMessage): CompatMessage => ({ ...msg, tool_call_id: 'parent' }))
        const engine: DispatchEngine = {
            dispatch: jest.fn().mockReturnValue([{ role: 'assistant (tool result)', content: 'r' }]),
            coercer: { buildMessage: jest.fn(), stamp },
        }
        const rule = new DelegateEachRule(new Pattern({}), [], new LiteralExpr(['x']), {
            toolCallId: new LiteralExpr('parent'),
        })
        expect(rule.produce(scope, engine, false, 0)).toEqual([
            { role: 'assistant (tool result)', content: 'r', tool_call_id: 'parent' },
        ])
        expect(stamp).toHaveBeenCalledTimes(1)
    })

    it('skips elements that match no recipe', () => {
        const dispatch = jest
            .fn()
            .mockReturnValueOnce(NO_MATCH)
            .mockReturnValueOnce([{ role: 'user', content: 'kept' }])
        const engine: DispatchEngine = { dispatch, coercer: { buildMessage: jest.fn(), stamp: jest.fn() } }

        const rule = new DelegateEachRule(new Pattern({}), [], new LiteralExpr(['skip', 'keep']), null)
        expect(rule.produce(scope, engine, false, 0)).toEqual([{ role: 'user', content: 'kept' }])
    })

    it('returns nothing for a non-array source', () => {
        const engine: DispatchEngine = { dispatch: jest.fn(), coercer: { buildMessage: jest.fn(), stamp: jest.fn() } }
        const rule = new DelegateEachRule(new Pattern({}), [], new LiteralExpr('not an array'), null)
        expect(rule.produce(scope, engine, false, 0)).toEqual([])
        expect(engine.dispatch).not.toHaveBeenCalled()
    })
})
