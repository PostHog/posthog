import type { Message } from './llmPlaygroundPromptsLogic'
import { isMessageSendable, toProviderMessages } from './playgroundMessageMapping'

describe('playgroundMessageMapping', () => {
    it('maps a tool-calling exchange to content blocks and merges consecutive tool results into one user turn', () => {
        const messages: Message[] = [
            { role: 'user', content: 'Weather in Paris and Rome?' },
            {
                role: 'assistant',
                content: 'Checking both.',
                toolCalls: [
                    { id: 'call_1', name: 'get_weather', arguments: '{"location": "Paris"}' },
                    { id: 'call_2', name: 'get_weather', arguments: '{"location": "Rome"}' },
                ],
            },
            { role: 'tool', content: 'Sunny, 21C', toolCallId: 'call_1', toolName: 'get_weather' },
            { role: 'tool', content: 'Cloudy, 18C', toolCallId: 'call_2', toolName: 'get_weather' },
            { role: 'user', content: 'Which is warmer?' },
        ]

        expect(toProviderMessages(messages)).toEqual([
            { role: 'user', content: 'Weather in Paris and Rome?' },
            {
                role: 'assistant',
                content: [
                    { type: 'text', text: 'Checking both.' },
                    { type: 'tool_use', id: 'call_1', name: 'get_weather', input: { location: 'Paris' } },
                    { type: 'tool_use', id: 'call_2', name: 'get_weather', input: { location: 'Rome' } },
                ],
            },
            {
                role: 'user',
                content: [
                    { type: 'tool_result', tool_use_id: 'call_1', content: 'Sunny, 21C' },
                    { type: 'tool_result', tool_use_id: 'call_2', content: 'Cloudy, 18C' },
                ],
            },
            { role: 'user', content: 'Which is warmer?' },
        ])
    })

    it.each([
        ['unparseable JSON', 'not json', 'not json'],
        ['a non-object JSON value', '[1, 2]', '[1, 2]'],
        ['an empty string', '', {}],
    ])('passes %s tool call arguments through instead of substituting them', (_, args, expectedInput) => {
        const result = toProviderMessages([
            { role: 'assistant', content: '', toolCalls: [{ id: 'call_1', name: 'lookup', arguments: args }] },
        ])

        expect(result).toEqual([
            {
                role: 'assistant',
                content: [{ type: 'tool_use', id: 'call_1', name: 'lookup', input: expectedInput }],
            },
        ])
    })

    it.each([
        ['an empty user message', { role: 'user', content: '  ' } as Message, false],
        [
            'an assistant message with only tool calls',
            { role: 'assistant', content: '', toolCalls: [{ id: 'c', name: 'f', arguments: '{}' }] } as Message,
            true,
        ],
        ['a tool message with empty content', { role: 'tool', content: '', toolCallId: 'c' } as Message, true],
    ])('counts %s as sendable: %p', (_, message, expected) => {
        expect(isMessageSendable(message)).toBe(expected)
    })
})
