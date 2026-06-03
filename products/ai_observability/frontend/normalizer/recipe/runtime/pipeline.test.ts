import { CompatMessage } from '../../../types'
import { ExistsPredicate, Pattern } from '../ast/predicate'
import { Rule } from '../ast/rule'
import { Recipe } from '../spec/recipe'
import { NO_MATCH, RecipePipeline } from './pipeline'

jest.mock('posthog-js', () => ({ __esModule: true, default: { capture: jest.fn() } }))

const MATCH_ALL = new Pattern({})
const MATCH_NONE = new Pattern({ __absent: new ExistsPredicate(true) })

class StubRule extends Rule {
    constructor(
        on: Pattern,
        private readonly messages: CompatMessage[]
    ) {
        super(on, [])
    }
    produce(): CompatMessage[] {
        return this.messages
    }
}

const recipe = (id: string, priority: number, rule: Rule): Recipe => ({ id, priority, rules: [rule] })

describe('RecipePipeline', () => {
    it('dispatches to the matching rule and returns its messages', () => {
        const messages: CompatMessage[] = [{ role: 'user', content: 'hi' }]
        const pipeline = new RecipePipeline([recipe('only', 100, new StubRule(MATCH_ALL, messages))])
        expect(pipeline.run({ role: 'user' }, 'user')).toEqual(messages)
    })

    it('when several recipes match, the lowest priority number wins', () => {
        const high = recipe('high', 200, new StubRule(MATCH_ALL, [{ role: 'user', content: 'low-priority' }]))
        const low = recipe('low', 1, new StubRule(MATCH_ALL, [{ role: 'user', content: 'high-priority' }]))
        const pipeline = new RecipePipeline([high, low])
        expect(pipeline.run({ role: 'user' }, 'user')).toEqual([{ role: 'user', content: 'high-priority' }])
    })

    it('returns NO_MATCH when no rule matches', () => {
        const pipeline = new RecipePipeline([recipe('none', 100, new StubRule(MATCH_NONE, []))])
        expect(pipeline.run({ role: 'user' }, 'user')).toBe(NO_MATCH)
    })

    it('throws when recursion exceeds the max delegation depth', () => {
        const pipeline = new RecipePipeline([recipe('only', 100, new StubRule(MATCH_ALL, []))])
        expect(() => pipeline.dispatch({ role: 'user' }, 'user', 11)).toThrow(/max depth/)
    })
})
