import { CompatMessage } from '../../../../types'
import { Scope } from '../../scope'
import { FollowupSpec } from '../../spec/emitSpec'
import { LiteralExpr } from '../expr'
import { Pattern } from '../predicate'
import { Rule } from './base'
import { DispatchEngine } from './dispatch'

// buildFollowups is concrete on the abstract base; a no-op subclass exposes it.
class TestRule extends Rule {
    produce(): CompatMessage[] {
        return []
    }
}

const scope = Scope.forNode({ role: 'user' }, 'user')

function engineBuilding(build: DispatchEngine['coercer']['buildMessage']): DispatchEngine {
    return { dispatch: jest.fn(), coercer: { buildMessage: build, stamp: jest.fn() } }
}

describe('Rule.buildFollowups', () => {
    it('builds a static followup message', () => {
        const followups: FollowupSpec[] = [{ kind: 'static', emit: {} }]
        const message: CompatMessage = { role: 'system', content: 'note' }
        const rule = new TestRule(new Pattern({}), followups)
        expect(rule.buildFollowups(scope, engineBuilding(jest.fn().mockReturnValue(message)))).toEqual([message])
    })

    it('expands an array into one message per element', () => {
        const followups: FollowupSpec[] = [{ kind: 'expand', from: new LiteralExpr(['a', 'b']), each: {} }]
        const rule = new TestRule(new Pattern({}), followups)
        const build = jest.fn((_emit, s: Scope): CompatMessage => ({ role: 'user', content: s.input as string }))
        expect(rule.buildFollowups(scope, engineBuilding(build))).toEqual([
            { role: 'user', content: 'a' },
            { role: 'user', content: 'b' },
        ])
    })

    it('drops followups the coercer rejects', () => {
        const followups: FollowupSpec[] = [{ kind: 'static', emit: {} }]
        const rule = new TestRule(new Pattern({}), followups)
        expect(rule.buildFollowups(scope, engineBuilding(jest.fn().mockReturnValue(null)))).toEqual([])
    })

    it('an expand over a non-array yields no followups', () => {
        const followups: FollowupSpec[] = [{ kind: 'expand', from: new LiteralExpr('not an array'), each: {} }]
        const rule = new TestRule(new Pattern({}), followups)
        const build = jest.fn()
        expect(rule.buildFollowups(scope, engineBuilding(build))).toEqual([])
        expect(build).not.toHaveBeenCalled()
    })
})
