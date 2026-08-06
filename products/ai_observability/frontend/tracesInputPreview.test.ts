import { pickLastInputMessage } from './AIObservabilityTracesScene'

describe('pickLastInputMessage', () => {
    it('returns null for empty or unusable input', () => {
        expect(pickLastInputMessage(null)).toBeNull()
        expect(pickLastInputMessage([])).toBeNull()
    })

    it('picks the most recent user turn from a multi-turn conversation', () => {
        const conversation = [
            { role: 'system', content: 'You are helpful.' },
            { role: 'user', content: 'first question' },
            { role: 'assistant', content: 'first answer' },
            { role: 'user', content: 'latest question' },
        ]
        expect(pickLastInputMessage(conversation)).toEqual({ role: 'user', content: 'latest question' })
    })

    it('unwraps a { messages } state container before picking the last user turn', () => {
        const state = {
            messages: [
                { role: 'user', content: 'old' },
                { role: 'assistant', content: 'reply' },
                { role: 'user', content: 'new' },
            ],
        }
        expect(pickLastInputMessage(state)).toEqual({ role: 'user', content: 'new' })
    })

    it('falls back to the last non-system message when there is no user turn', () => {
        const conversation = [
            { role: 'system', content: 'You are helpful.' },
            { role: 'assistant', content: 'tool result' },
        ]
        expect(pickLastInputMessage(conversation)).toEqual({ role: 'assistant', content: 'tool result' })
    })

    it('rejects unknown state-wrapper shapes in strict mode', () => {
        expect(pickLastInputMessage({ current_step: 3 }, { strict: true })).toBeNull()
    })
})
