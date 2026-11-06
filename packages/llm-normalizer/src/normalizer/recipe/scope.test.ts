import { Scope } from './scope'

describe('Scope', () => {
    describe('forNode', () => {
        it("resolves the role from the input's role field", () => {
            expect(Scope.forNode({ role: 'assistant' }, 'user').role).toBe('assistant')
        })

        it('resolves the role from a recognized type field', () => {
            // 'human' is a known provider alias for the user role
            expect(Scope.forNode({ type: 'human' }, 'assistant').role).toBe('user')
        })

        it('falls back to the inherited role for input without a role', () => {
            expect(Scope.forNode({ content: 'hi' }, 'assistant').role).toBe('assistant')
            expect(Scope.forNode('a bare string', 'user').role).toBe('user')
        })
    })

    describe('withInput', () => {
        it('swaps the value but keeps the resolved role', () => {
            const parent = Scope.forNode({ role: 'assistant', items: [1] }, 'user')
            const child = parent.withInput({ nested: true })
            expect(child.input).toEqual({ nested: true })
            expect(child.role).toBe('assistant')
        })
    })
})
