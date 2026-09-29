import { ThreadMessagesOptions, isMessageIO, toThreadMessages } from './toThreadMessages'

const options = (
    defaultRole: 'user' | 'assistant',
    idPrefix: string,
    sourceNodeId: string | null
): ThreadMessagesOptions => ({ defaultRole, idPrefix, sourceNodeId, teamId: 7 })

describe('toThreadMessages', () => {
    it('keeps roles and text in order, mapping the OpenAI developer role to system', () => {
        const messages = toThreadMessages(
            [
                { role: 'system', content: 'Answer billing questions.' },
                { role: 'developer', content: 'Follow the house style.' },
                { role: 'user', content: 'Why did my invoice go up?' },
            ],
            options('user', 'in', 'gen-1')
        )
        expect(messages.map((m) => [m.role, m.parts])).toEqual([
            ['system', [{ kind: 'text', text: 'Answer billing questions.' }]],
            ['system', [{ kind: 'text', text: 'Follow the house style.' }]],
            ['user', [{ kind: 'text', text: 'Why did my invoice go up?' }]],
        ])
        expect(messages[0]).toMatchObject({ id: 'in-0', sourceNodeId: 'gen-1', isInternal: false })
    })

    it('pairs tool results with their calls instead of repeating them as messages', () => {
        const messages = toThreadMessages(
            [
                {
                    role: 'assistant',
                    content: '',
                    tool_calls: [
                        {
                            type: 'function',
                            id: 'call-1',
                            function: { name: 'lookup_invoice', arguments: '{"month":"2026-08"}' },
                        },
                    ],
                },
                { role: 'tool', tool_call_id: 'call-1', content: '{"total_usd":180}' },
                { role: 'assistant', content: 'Two seats were added.' },
            ],
            options('assistant', 'out', 'gen-1')
        )
        expect(messages).toHaveLength(2)
        expect(messages[0].parts).toEqual([
            { kind: 'toolCall', name: 'lookup_invoice', args: { month: '2026-08' }, result: '{"total_usd":180}' },
        ])
        expect(messages[0].isInternal).toBe(true)
        expect(messages[1]).toMatchObject({ role: 'assistant', isInternal: false })
    })

    it('marks unmatched tool results as internal tool messages', () => {
        const [message] = toThreadMessages(
            [{ role: 'tool', tool_call_id: 'gone', content: 'late result' }],
            options('user', 'in', null)
        )
        expect(message).toMatchObject({
            role: 'tool',
            isInternal: true,
            parts: [{ kind: 'text', text: 'late result' }],
        })
    })

    it('turns non-text content items into attachments', () => {
        const [message] = toThreadMessages(
            [
                {
                    role: 'user',
                    content: [
                        { type: 'text', text: 'What is in this receipt?' },
                        { type: 'image_url', image_url: { url: 'https://example.com/r.png' } },
                    ],
                },
            ],
            options('user', 'in', null)
        )
        expect(message.parts).toEqual([
            { kind: 'text', text: 'What is in this receipt?' },
            {
                kind: 'attachment',
                mediaType: 'image',
                name: null,
                mimeType: null,
                url: 'https://example.com/r.png',
            },
        ])
    })

    it('reads a media item the normalizer passed through as JSON text as an attachment', () => {
        const messages = toThreadMessages(
            [
                {
                    role: 'user',
                    content: [
                        { type: 'text', text: 'Transcribe this.' },
                        { type: 'input_audio', input_audio: { data: 'UklGRg==', format: 'mp3' } },
                    ],
                },
            ],
            options('user', 'in', null)
        )
        expect(messages.flatMap((message) => message.parts)).toEqual([
            { kind: 'text', text: 'Transcribe this.' },
            {
                kind: 'attachment',
                mediaType: 'audio',
                name: null,
                mimeType: 'audio/mp3',
                url: 'data:audio/mp3;base64,UklGRg==',
            },
        ])
    })

    it('keeps the text and reasoning summary of OpenAI Responses output items', () => {
        const messages = toThreadMessages(
            [
                {
                    type: 'reasoning',
                    id: 'rs_1',
                    summary: [{ type: 'summary_text', text: 'Compare the two plans by seat price.' }],
                },
                {
                    type: 'message',
                    id: 'msg_1',
                    role: 'assistant',
                    status: 'completed',
                    content: [{ type: 'output_text', text: 'The team plan is cheaper for 5 seats.', annotations: [] }],
                },
            ],
            options('assistant', 'out', 'gen-1')
        )
        expect(messages.map((message) => [message.role, message.parts, message.isInternal])).toEqual([
            ['assistant', [{ kind: 'thinking', text: 'Compare the two plans by seat price.' }], true],
            ['assistant', [{ kind: 'text', text: 'The team plan is cheaper for 5 seats.' }], false],
        ])
    })

    it('returns nothing for empty input', () => {
        expect(toThreadMessages(null, options('user', 'in', null))).toEqual([])
    })

    it('pairs an Anthropic tool_use with a tool_result carried on a later message, and keeps thinking separate', () => {
        const messages = toThreadMessages(
            [
                {
                    role: 'assistant',
                    content: [
                        { type: 'thinking', thinking: 'Let me check the invoice.' },
                        { type: 'tool_use', id: 'call-1', name: 'lookup_invoice', input: { month: '2026-08' } },
                    ],
                },
                {
                    role: 'user',
                    content: [{ type: 'tool_result', tool_use_id: 'call-1', content: '{"total_usd":180}' }],
                },
            ],
            options('assistant', 'gen', 'gen-1')
        )
        expect(messages).toHaveLength(2)
        expect(messages[0]).toMatchObject({
            isInternal: true,
            parts: [{ kind: 'thinking', text: 'Let me check the invoice.' }],
        })
        expect(messages[1]).toMatchObject({
            isInternal: true,
            parts: [
                { kind: 'toolCall', name: 'lookup_invoice', args: { month: '2026-08' }, result: '{"total_usd":180}' },
            ],
        })
    })

    it.each<[string, unknown, unknown, boolean]>([
        ['role-bearing arrays', [{ role: 'user', content: 'Hi' }], [{ role: 'assistant', content: 'Hello' }], true],
        ['LangChain message dicts', [{ type: 'human', content: 'Hi' }], null, true],
        ['workflow step arrays', [{ step: 1 }, { step: 2 }], [{ step: 3 }], false],
        ['an array mixing messages and state', [{ role: 'user', content: 'Hi' }, { step: 1 }], null, false],
        ['state objects', { question: 'Hi' }, { answer: 'Hello' }, false],
        ['a string next to a step array', [{ step: 1 }, { step: 2 }], 'done', false],
        ['a string next to a role array', [{ role: 'user', content: 'Hi' }], 'Hello', true],
        ['strings on both sides', 'Hi', 'Hello', false],
    ])('isMessageIO treats %s correctly', (_name, input, output, expected) => {
        expect(isMessageIO(input, output)).toBe(expected)
    })
})
