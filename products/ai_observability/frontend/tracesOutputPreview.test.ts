import { pickLastOutputMessage } from './AIObservabilityTracesScene'

describe('pickLastOutputMessage', () => {
    it('returns null for empty or unusable input', () => {
        expect(pickLastOutputMessage(null)).toBeNull()
        expect(pickLastOutputMessage([])).toBeNull()
    })

    it('skips a trailing tool call and picks the last user-facing assistant answer', () => {
        const conversation = [
            { role: 'user', content: 'what is the weather?' },
            { role: 'assistant', content: 'It is 72F.' },
            {
                role: 'assistant',
                content: '',
                tool_calls: [{ id: 'c1', type: 'function', function: { name: 'get_weather', arguments: '{}' } }],
            },
        ]
        expect(pickLastOutputMessage(conversation)).toMatchObject({ role: 'assistant', content: 'It is 72F.' })
    })

    it('skips a trailing tool result and picks the last assistant answer', () => {
        const conversation = [
            { role: 'assistant', content: 'Let me check.' },
            {
                role: 'assistant',
                content: '',
                tool_calls: [{ id: 'c1', type: 'function', function: { name: 'get_weather', arguments: '{}' } }],
            },
            { role: 'tool', content: '72F', tool_call_id: 'c1' },
        ]
        expect(pickLastOutputMessage(conversation)).toMatchObject({ role: 'assistant', content: 'Let me check.' })
    })

    it('keeps an assistant message that mixes real text with a tool call', () => {
        const conversation = [
            { role: 'user', content: 'book a table' },
            {
                role: 'assistant',
                content: 'Booking that now.',
                tool_calls: [{ id: 'c1', type: 'function', function: { name: 'book', arguments: '{}' } }],
            },
        ]
        expect(pickLastOutputMessage(conversation)).toMatchObject({
            role: 'assistant',
            content: 'Booking that now.',
        })
    })

    it('falls back to the tool call when the trace has nothing but tool traffic', () => {
        const conversation = [
            { role: 'user', content: 'what is the weather?' },
            {
                role: 'assistant',
                content: '',
                tool_calls: [{ id: 'c1', type: 'function', function: { name: 'get_weather', arguments: '{}' } }],
            },
        ]
        const picked = pickLastOutputMessage(conversation)
        expect(picked).not.toBeNull()
        expect(picked?.tool_calls?.[0]?.function?.name).toBe('get_weather')
    })

    it('unwraps a { messages } state container before picking the output', () => {
        const state = {
            messages: [
                { role: 'assistant', content: 'final answer' },
                { role: 'tool', content: 'tool output', tool_call_id: 'c1' },
            ],
        }
        expect(pickLastOutputMessage(state)).toMatchObject({ role: 'assistant', content: 'final answer' })
    })
})
