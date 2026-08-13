import { CompatMessage } from '../../../../types'
import { Scope } from '../../scope'
import { Pattern } from '../predicate'
import { Rule } from './base'
import { DispatchEngine } from './dispatch'
import { EmitRule } from './emit'

const scope = Scope.forNode({ role: 'user' }, 'user')

function engineReturning(message: CompatMessage | null): DispatchEngine {
    return {
        dispatch: jest.fn(),
        coercer: { buildMessage: jest.fn().mockReturnValue(message), stamp: jest.fn() },
    }
}

describe('EmitRule', () => {
    it('produces a single message from the emit spec', () => {
        const message: CompatMessage = { role: 'user', content: 'hi' }
        const rule: Rule = new EmitRule(new Pattern({}), [], {})
        expect(rule.produce(scope, engineReturning(message), false, 0)).toEqual([message])
    })

    it('produces nothing when the coercer drops an empty message', () => {
        const rule: Rule = new EmitRule(new Pattern({}), [], {})
        expect(rule.produce(scope, engineReturning(null), true, 0)).toEqual([])
    })
})
