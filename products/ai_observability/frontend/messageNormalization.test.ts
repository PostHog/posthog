import { normalizeMessage, normalizeMessages } from './messageNormalization'

describe('messageNormalization', () => {
    describe('delegates to the recipe normalizer', () => {
        it('normalizeMessage normalizes a single message', () => {
            expect(normalizeMessage({ role: 'assistant', content: 'hi' }, 'user')).toEqual([
                { role: 'assistant', content: 'hi' },
            ])
        })

        it('normalizeMessages prepends an available-tools pseudo-message when tools are passed', () => {
            const result = normalizeMessages({ role: 'user', content: 'hi' }, 'user', [{ name: 'search' }])
            expect(result[0]).toEqual({ role: 'available tools', content: '', tools: [{ name: 'search' }] })
        })

        it('normalizeMessages carries no message for nullish/scalar input', () => {
            expect(normalizeMessages(null, 'user')).toEqual([])
            expect(normalizeMessages(42, 'user')).toEqual([])
        })
    })
})
