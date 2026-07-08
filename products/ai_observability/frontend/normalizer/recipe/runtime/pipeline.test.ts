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

const recipe = (id: string, rule: Rule): Recipe => ({ id, rules: [rule] })

describe('RecipePipeline', () => {
    it('dispatches to the matching rule and returns its messages as recognized', () => {
        const messages: CompatMessage[] = [{ role: 'user', content: 'hi' }]
        const pipeline = new RecipePipeline([recipe('only', new StubRule(MATCH_ALL, messages))])
        expect(pipeline.run({ role: 'user' }, 'user')).toEqual({ messages, recognized: true })
    })

    it('when several recipes match, the first in order wins', () => {
        const first = recipe('first', new StubRule(MATCH_ALL, [{ role: 'user', content: 'first-wins' }]))
        const second = recipe('second', new StubRule(MATCH_ALL, [{ role: 'user', content: 'second' }]))
        const pipeline = new RecipePipeline([first, second])
        expect(pipeline.run({ role: 'user' }, 'user')).toEqual({
            messages: [{ role: 'user', content: 'first-wins' }],
            recognized: true,
        })
    })

    it('salvages input no recipe claims by stringifying it, reported as unrecognized', () => {
        const pipeline = new RecipePipeline([recipe('none', new StubRule(MATCH_NONE, []))])
        expect(pipeline.run({ weird: true }, 'user')).toEqual({
            messages: [{ role: 'user', content: '{"weird":true}' }],
            recognized: false,
        })
    })

    it('salvages a string `content` field as-is rather than stringifying the wrapper', () => {
        const pipeline = new RecipePipeline([recipe('none', new StubRule(MATCH_NONE, []))])
        expect(pipeline.run({ content: 'hi', extra: 1 }, 'assistant')).toEqual({
            messages: [{ role: 'assistant', content: 'hi' }],
            recognized: false,
        })
    })

    it('dispatch (delegation) salvages an unmatched child so it is not dropped', () => {
        const pipeline = new RecipePipeline([recipe('none', new StubRule(MATCH_NONE, []))])
        expect(pipeline.dispatch({ weird: true }, 'user', 0)).toEqual([{ role: 'user', content: '{"weird":true}' }])
    })

    it('dispatch (delegation) returns NO_MATCH for undefined so a delegating rule drops it', () => {
        const pipeline = new RecipePipeline([recipe('none', new StubRule(MATCH_NONE, []))])
        expect(pipeline.dispatch(undefined, 'user', 0)).toBe(NO_MATCH)
    })

    it('throws when recursion exceeds the max delegation depth', () => {
        const pipeline = new RecipePipeline([recipe('only', new StubRule(MATCH_ALL, []))])
        expect(() => pipeline.dispatch({ role: 'user' }, 'user', 11)).toThrow(/max depth/)
    })
})
