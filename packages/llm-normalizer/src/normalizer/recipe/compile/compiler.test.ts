import { CompatMessage } from '../../../types'
import { DispatchEngine, NO_MATCH } from '../ast/rule'
import { SlotCoercer } from '../runtime/coercion'
import { Scope } from '../scope'
import { compileRecipe } from './compiler'

const ENGINE: DispatchEngine = { dispatch: () => NO_MATCH, coercer: new SlotCoercer() }
const INPUT = { name: 'Ada', items: ['a', 'b'] }

// Compile a one-rule recipe and produce its message, so we can observe how the
// compiler wired a value expression (trusting the AST nodes + coercer).
function emitContent(content: unknown, input: unknown = INPUT): CompatMessage['content'] {
    const recipe = compileRecipe({ id: 't', rules: [{ on: {}, emit: { content } }] })
    return recipe.rules[0].produce(Scope.forNode(input, 'user'), ENGINE, false, 0)[0]?.content
}

describe('compileRecipe', () => {
    it('compiles a full recipe into runnable rules', () => {
        const recipe = compileRecipe({ id: 'greet', rules: [{ on: {}, emit: { content: 'hi' } }] })
        expect(recipe.id).toBe('greet')
        const produced = recipe.rules[0].produce(Scope.forNode({}, 'user'), ENGINE, false, 0)
        expect(produced).toEqual([{ role: 'user', content: 'hi' }])
    })

    it('a $.field string compiles to a value that reads that field', () => {
        expect(emitContent('$.name')).toBe('Ada')
    })

    it('an interpolation string compiles to a value that splices fields into text', () => {
        expect(emitContent('hello $.name!')).toBe('hello Ada!')
    })

    it('a one-key operator object compiles to that operator', () => {
        expect(emitContent({ join: { from: '$.items', sep: ',' } })).toBe('a,b')
    })

    it('a bare scalar field compiles to an equality predicate', () => {
        const recipe = compileRecipe({ id: 't', rules: [{ on: { type: 'reasoning' }, emit: {} }] })
        expect(recipe.rules[0].on.matches({ type: 'reasoning' })).toBe(true)
        expect(recipe.rules[0].on.matches({ type: 'text' })).toBe(false)
    })

    it('literal: preserves a one-key object that collides with an operator name', () => {
        // Bare `{ join: 'x' }` is read as the join operator, which rejects a non-mapping arg.
        expect(() => emitContent({ join: 'x' })).toThrow(/takes a mapping/)
        // Wrapped in `literal:`, the same object is kept as plain data (surfaced here via spread).
        const recipe = compileRecipe({ id: 't', rules: [{ on: {}, emit: { spread: { literal: { join: 'x' } } } }] })
        const message = recipe.rules[0].produce(Scope.forNode({}, 'user'), ENGINE, false, 0)[0]
        expect(message.join).toBe('x')
    })

    it('throws a helpful "did you mean" error for an unknown operator', () => {
        expect(() => emitContent({ jon: { from: '$.items' } })).toThrow(/Did you mean 'join'/)
    })

    it('throws when a rule sets none of emit, delegate, or delegateEach', () => {
        expect(() => compileRecipe({ id: 't', rules: [{ on: {} }] })).toThrow(/emit, delegate, delegateEach/)
    })

    it.each([
        ['missing id', { rules: [] }, /missing an 'id'/],
        ['missing rules', { id: 't' }, /missing a 'rules:'/],
    ])('throws when %s', (_label, raw, expected) => {
        expect(() => compileRecipe(raw)).toThrow(expected)
    })

    it('throws when a predicate mixes multiple verbs', () => {
        const raw = { id: 't', rules: [{ on: { field: { equals: 1, exists: true } }, emit: {} }] }
        expect(() => compileRecipe(raw)).toThrow(/multiple verbs/)
    })
})
