import posthog from 'posthog-js'

import { CompatMessage } from '../types'
import {
    buildStreamItems,
    captureUnrenderableMessageOnce,
    hasNonTextContent,
    unrenderableContentKinds,
} from './TranscriptBubbleStream'

jest.mock('posthog-js', () => ({
    __esModule: true,
    default: { capture: jest.fn() },
}))

const mockedCapture = posthog.capture as jest.Mock

beforeEach(() => mockedCapture.mockClear())

// Shared message-builder helpers used across the buildStreamItems suites.
const userText = (text: string): CompatMessage => ({ role: 'user', content: text })
const assistant = (text: string): CompatMessage => ({ role: 'assistant', content: text })
const thinking = (text: string): CompatMessage => ({ role: 'assistant (thinking)', content: text })
const toolResult = (text: string): CompatMessage =>
    ({ role: 'assistant (tool result)', content: text, tool_call_id: 'toolu_1' }) as unknown as CompatMessage

describe('hasNonTextContent', () => {
    it.each<[name: string, content: CompatMessage['content'], expected: boolean]>([
        ['returns false for a plain string content', 'Hello there', false],
        ['returns false for an empty array', [], false],
        ['returns false for content with only text items', [{ type: 'text', text: 'Hi' }], false],
        [
            'returns false for Vercel SDK text parts (`{ type: "text", content }`)',
            [{ type: 'text', content: 'Hi from Vercel SDK' }] as unknown as CompatMessage['content'],
            false,
        ],
        [
            'returns false for Vercel SDK input_text parts',
            [{ type: 'input_text', text: 'Hi' }] as unknown as CompatMessage['content'],
            false,
        ],
        [
            'returns true for a thinking part — reasoning is routed to "Show steps", not the bubble',
            [
                { type: 'thinking', thinking: 'let me work through this', signature: 'sig' },
            ] as unknown as CompatMessage['content'],
            true,
        ],
        [
            'returns false for content with only tool-step items (steps panel covers them)',
            [
                { type: 'function', function: { name: 'get_weather' } },
                { type: 'tool_use', id: 'toolu_1', name: 'search_docs', input: {} },
                { type: 'tool_result', tool_use_id: 'toolu_1', content: 'ok' },
                { type: 'tool-call', toolCallId: 'a', toolName: 'search_docs', input: {} },
                { type: 'function_call', call_id: 'c1', name: 'search_docs', arguments: '{}' },
            ] as unknown as CompatMessage['content'],
            false,
        ],
        [
            'returns true for content with an image item',
            [
                { type: 'image_url', image_url: { url: 'https://example.com/a.png' } },
            ] as unknown as CompatMessage['content'],
            true,
        ],
        [
            'returns true for content with a file item',
            [
                {
                    type: 'file',
                    file: { filename: 'report.pdf', file_data: 'data:application/pdf;base64,AAA' },
                },
            ] as unknown as CompatMessage['content'],
            true,
        ],
        [
            'returns true for content with an audio item',
            [{ type: 'audio', data: 'AAA', mime_type: 'audio/wav' }] as unknown as CompatMessage['content'],
            true,
        ],
        [
            'returns true for an unrecognized item shape',
            [{ type: 'video', src: 'foo' }] as unknown as CompatMessage['content'],
            true,
        ],
        [
            'returns true when text co-exists with non-text — text co-existence does not suppress the signal',
            [
                { type: 'text', text: 'Look at this:' },
                { type: 'image_url', image_url: { url: 'https://example.com/a.png' } },
            ] as unknown as CompatMessage['content'],
            true,
        ],
        [
            'returns true when a tool call sits alongside an image (tool call filtered, image surfaces)',
            [
                { type: 'tool_use', id: 'toolu_1', name: 'search_docs', input: {} },
                { type: 'image_url', image_url: { url: 'https://example.com/a.png' } },
            ] as unknown as CompatMessage['content'],
            true,
        ],
    ])('%s', (_, content, expected) => {
        const message: CompatMessage = { role: 'user', content }
        expect(hasNonTextContent(message)).toBe(expected)
    })
})

describe('unrenderableContentKinds', () => {
    it('returns the distinct sorted set of unrenderable item type discriminators', () => {
        const message: CompatMessage = {
            role: 'user',
            content: [
                { type: 'text', text: 'Look at these:' },
                { type: 'image_url', image_url: { url: 'a' } },
                { type: 'image_url', image_url: { url: 'b' } },
                { type: 'file', file: { filename: 'f', file_data: 'd' } },
                { type: 'tool_use', id: 'toolu_1', name: 'x', input: {} },
            ] as unknown as CompatMessage['content'],
        }
        expect(unrenderableContentKinds(message)).toEqual(['file', 'image_url'])
    })

    it('returns [] for content with no unrenderable items', () => {
        expect(unrenderableContentKinds({ role: 'user', content: 'Hi' })).toEqual([])
        expect(unrenderableContentKinds({ role: 'user', content: [{ type: 'text', text: 'Hi' }] })).toEqual([])
    })
})

describe('buildStreamItems — internal tag detection + grouping', () => {
    const userTypedInternal = (text: string): CompatMessage => ({
        role: 'user',
        content: [{ type: 'text', text }] as unknown as CompatMessage['content'],
    })

    it('returns plain bubbles for a conversation with no internal tags', () => {
        const items = buildStreamItems([userText('Hi there'), assistant('Hello')])
        expect(items.map((i) => i.kind)).toEqual(['bubble', 'bubble'])
    })

    it('groups a single internal-tag-only user message into a one-pill group', () => {
        const items = buildStreamItems([userText('<system_reminder>foo</system_reminder>')])
        expect(items).toHaveLength(1)
        expect(items[0].kind).toBe('internal-group')
        if (items[0].kind === 'internal-group') {
            expect(items[0].labels).toEqual(['system_reminder'])
            expect(items[0].messages).toHaveLength(1)
        }
    })

    it('groups consecutive internal tag messages into a single pill', () => {
        // Four internal tag messages, then the user's real question.
        const items = buildStreamItems([
            userTypedInternal('<system_reminder>foo</system_reminder>'),
            userTypedInternal('<system_reminder>\nbar\n</system_reminder>'),
            userTypedInternal('<voice_mode>off</voice_mode>'),
            userTypedInternal('<attached_context>\nbaz\n</attached_context>'),
            userText('what changed?'),
            assistant('looking into it...'),
        ])
        expect(items.map((i) => i.kind)).toEqual(['internal-group', 'bubble', 'bubble'])
        if (items[0].kind === 'internal-group') {
            expect(items[0].messages).toHaveLength(4)
            expect(items[0].labels).toEqual(['system_reminder', 'system_reminder', 'voice_mode', 'attached_context'])
        }
        if (items[1].kind === 'bubble') {
            expect(items[1].text).toBe('what changed?')
        }
    })

    it('breaks grouping when a bubble interrupts the internal tag run', () => {
        // [internal, bubble, internal] should produce TWO groups, not one — the
        // pill marks chronological position, not "all internal tags ever".
        const items = buildStreamItems([
            userText('<system_reminder>a</system_reminder>'),
            userText('first question'),
            userText('<voice_mode>off</voice_mode>'),
            assistant('reply'),
        ])
        expect(items.map((i) => i.kind)).toEqual(['internal-group', 'bubble', 'internal-group', 'bubble'])
    })

    it('does not classify an assistant-role wrapper as internal (models can emit `<system_reminder>` in output)', () => {
        const items = buildStreamItems([
            userText('hi'),
            // Unusual but legal: an assistant reply that contains an internal-tag-looking wrapper. Render it.
            { role: 'assistant', content: '<system_reminder>foo</system_reminder>' },
        ])
        expect(items.map((i) => i.kind)).toEqual(['bubble', 'bubble'])
    })

    it('does not classify a wrapper-plus-extra-text user message as internal', () => {
        // User wrote actual text — we'd lose information by hiding it.
        const items = buildStreamItems([userText('foo <system_reminder>bar</system_reminder> baz')])
        expect(items.map((i) => i.kind)).toEqual(['bubble'])
    })

    it('does not classify unrelated wrapper tags as internal', () => {
        // `<thinking>` and friends are not in the allowlist — models can emit them as visible content.
        const items = buildStreamItems([
            userText('<thinking>foo</thinking>'),
            userText('<useful-context>foo</useful-context>'),
            userText('<answer>42</answer>'),
        ])
        expect(items.map((i) => i.kind)).toEqual(['bubble', 'bubble', 'bubble'])
    })

    it('drops `system`-role messages entirely (HIDDEN_ROLES) before internal tag classification', () => {
        const items = buildStreamItems([{ role: 'system', content: 'You are an assistant.' }, userText('hello')])
        expect(items.map((i) => i.kind)).toEqual(['bubble'])
    })

    it('keeps a single internal tag message sandwiched between bubbles intact (no merging across bubbles)', () => {
        const items = buildStreamItems([
            userText('first'),
            userText('<system_reminder>x</system_reminder>'),
            assistant('reply'),
        ])
        expect(items.map((i) => i.kind)).toEqual(['bubble', 'internal-group', 'bubble'])
        if (items[1].kind === 'internal-group') {
            expect(items[1].messages).toHaveLength(1)
        }
    })
})

describe('buildStreamItems — internal messages (thinking, tool_result) collapse into the same pill', () => {
    it('hides an assistant (thinking) bubble inside an internal-group pill', () => {
        const items = buildStreamItems([userText('What is 2+2?'), thinking('Let me work through this'), assistant('4')])
        expect(items.map((i) => i.kind)).toEqual(['bubble', 'internal-group', 'bubble'])
        if (items[1].kind === 'internal-group') {
            expect(items[1].labels).toEqual(['thinking'])
        }
    })

    it('hides an assistant (tool result) bubble inside an internal-group pill', () => {
        const items = buildStreamItems([
            userText('Look up the order'),
            toolResult('<row id="42">paid</row>'),
            assistant('Your order is paid.'),
        ])
        expect(items.map((i) => i.kind)).toEqual(['bubble', 'internal-group', 'bubble'])
        if (items[1].kind === 'internal-group') {
            expect(items[1].labels).toEqual(['tool_result'])
        }
    })

    it('collapses a thinking + tool_result run into a single pill', () => {
        const items = buildStreamItems([
            userText('Build me a funnel for trial conversions.'),
            thinking('First I need to look up the schema.'),
            toolResult('events: $pageview, signup_completed, trial_started, ...'),
            thinking('Now I can compose the funnel.'),
            toolResult('insight created: id=aqc0'),
            assistant("Here's your funnel: ..."),
        ])
        expect(items.map((i) => i.kind)).toEqual(['bubble', 'internal-group', 'bubble'])
        if (items[1].kind === 'internal-group') {
            expect(items[1].messages).toHaveLength(4)
            expect(items[1].labels).toEqual(['thinking', 'tool_result', 'thinking', 'tool_result'])
        }
    })

    it('produces separate pills when the final answer of one user turn precedes the next user turn', () => {
        const items = buildStreamItems([
            userText('Question one'),
            thinking('first round of reasoning'),
            toolResult('first tool result'),
            assistant('Answer to question one.'),
            userText('Question two'),
            thinking('second round of reasoning'),
            toolResult('second tool result'),
            assistant('Answer to question two.'),
        ])
        // 'Answer to question one.' stays a bubble: the next message is a genuine user turn, with no
        // tool activity before it — so it is a final answer, not intermediate narration.
        expect(items.map((i) => i.kind)).toEqual([
            'bubble',
            'internal-group',
            'bubble',
            'bubble',
            'internal-group',
            'bubble',
        ])
    })

    it('coalesces an internal tag + thinking + tool_result run into a single pill', () => {
        const items = buildStreamItems([
            userText('<system_reminder>be concise</system_reminder>'),
            thinking('let me think'),
            toolResult('lookup result'),
            assistant('done'),
        ])
        expect(items.map((i) => i.kind)).toEqual(['internal-group', 'bubble'])
        if (items[0].kind === 'internal-group') {
            expect(items[0].labels).toEqual(['system_reminder', 'thinking', 'tool_result'])
        }
    })

    it('hides a user-role message whose content is only Anthropic typed tool_result parts', () => {
        const userToolResultBlob: CompatMessage = {
            role: 'user',
            content: [
                { type: 'tool_result', tool_use_id: 't1', content: 'row 1' },
                { type: 'tool_result', tool_use_id: 't2', content: 'row 2' },
            ] as unknown as CompatMessage['content'],
        }
        const items = buildStreamItems([userText('Look up two orders'), userToolResultBlob, assistant('Done.')])
        expect(items.map((i) => i.kind)).toEqual(['bubble', 'internal-group', 'bubble'])
        if (items[1].kind === 'internal-group') {
            expect(items[1].labels).toEqual(['tool_result'])
        }
    })

    it('hides a custom `{type:"function", tool_name, content}` user-role tool result', () => {
        // No nested `function` object — distinguishes from a tool CALL.
        const userFunctionResult: CompatMessage = {
            role: 'user',
            content: [
                {
                    type: 'function',
                    tool_name: 'fetch_account_context',
                    content: '<current_account_data>...</current_account_data>',
                },
            ] as unknown as CompatMessage['content'],
        }
        const items = buildStreamItems([
            userText('What is this account?'),
            userFunctionResult,
            assistant('Summary: ...'),
        ])
        expect(items.map((i) => i.kind)).toEqual(['bubble', 'internal-group', 'bubble'])
        if (items[1].kind === 'internal-group') {
            expect(items[1].labels).toEqual(['tool_result'])
        }
    })

    it('does NOT hide a user-role message that mixes a tool_result part with real user text', () => {
        const mixed: CompatMessage = {
            role: 'user',
            content: [
                { type: 'tool_result', tool_use_id: 't1', content: 'data' },
                { type: 'text', text: 'please summarize the above' },
            ] as unknown as CompatMessage['content'],
        }
        const items = buildStreamItems([mixed])
        expect(items.map((i) => i.kind)).toEqual(['bubble'])
    })

    it('does NOT classify an assistant-role message whose text mentions "thinking" as internal', () => {
        // Only the synthetic `assistant (thinking)` role triggers hiding — not the substring.
        const items = buildStreamItems([{ role: 'assistant', content: 'I was thinking we should ...' }])
        expect(items.map((i) => i.kind)).toEqual(['bubble'])
    })

    it('preserves the role of the first hidden message on the group (alignment is label-based; role kept for analytics)', () => {
        const items = buildStreamItems([thinking('first reasoning step')])
        expect(items.map((i) => i.kind)).toEqual(['internal-group'])
        if (items[0].kind === 'internal-group') {
            expect(items[0].role).toBe('assistant (thinking)')
        }
    })

    it.each<[name: string, message: CompatMessage, expectedLabels: string[]]>([
        [
            'Anthropic typed tool_result parts (renders agent-side)',
            {
                role: 'user',
                content: [
                    { type: 'tool_result', tool_use_id: 't1', content: 'row 1' },
                    { type: 'tool_result', tool_use_id: 't2', content: 'row 2' },
                ] as unknown as CompatMessage['content'],
            },
            ['tool_result'],
        ],
        [
            'custom function-shape user-role tool_result',
            {
                role: 'user',
                content: [
                    {
                        type: 'function',
                        tool_name: 'fetch_account_context',
                        content: '<current_account_data>...</current_account_data>',
                    },
                ] as unknown as CompatMessage['content'],
            },
            ['tool_result'],
        ],
        [
            'internal tags under their tag-name label (renders user-side)',
            { role: 'user', content: '<system_reminder>foo</system_reminder>' },
            ['system_reminder'],
        ],
    ])('groups a single message into one internal-group: %s', (_, message, expectedLabels) => {
        const items = buildStreamItems([message])
        expect(items.map((i) => i.kind)).toEqual(['internal-group'])
        if (items[0].kind === 'internal-group') {
            expect(items[0].labels).toEqual(expectedLabels)
        }
    })
})

describe('buildStreamItems — intermediate assistant narration collapses, final answer stays', () => {
    const toolRole = (text: string): CompatMessage => ({ role: 'tool', content: text }) as unknown as CompatMessage
    const toolCall = (name: string): CompatMessage =>
        ({
            role: 'assistant',
            content: '',
            tool_calls: [{ type: 'function', id: 'toolu_1', function: { name, arguments: {} } }],
        }) as unknown as CompatMessage
    const assistantWithToolCall = (text: string, name: string): CompatMessage =>
        ({
            role: 'assistant',
            content: text,
            tool_calls: [{ type: 'function', id: 'toolu_1', function: { name, arguments: {} } }],
        }) as unknown as CompatMessage

    it('collapses Anthropic-style narration (split text msg) that precedes a tool result', () => {
        // What Max emits: [thinking, narration text, tool_use] -> normalizer splits into separate
        // messages; the narration text is followed by the tool_result of the call it made.
        const items = buildStreamItems([
            userText('What % of employees login web vs app'),
            thinking('Let me check the schema.'),
            assistant('The `$lib` property is the right signal here.'),
            toolResult('events: user_logged_in, login_succeeded, ...'),
            thinking('Now I can build the split.'),
            assistant("Over the last 30 days, here's the split: ..."),
        ])
        // One question bubble, one internal-group folding thinking + narration + tool_result +
        // thinking, then the final answer as a bubble.
        expect(items.map((i) => i.kind)).toEqual(['bubble', 'internal-group', 'bubble'])
        if (items[1].kind === 'internal-group') {
            expect(items[1].labels).toEqual(['thinking', 'reasoning', 'tool_result', 'thinking'])
        }
        if (items[2].kind === 'bubble') {
            expect(items[2].text).toBe("Over the last 30 days, here's the split: ...")
        }
    })

    it('collapses an assistant message that carries its own tool_calls (OpenAI chat / LangChain shape)', () => {
        const items = buildStreamItems([
            userText('What is the weather in Berlin?'),
            assistantWithToolCall('I should call the weather API.', 'get_weather'),
            toolRole('Sunny, 22°C.'),
            assistant('It is sunny and 22°C in Berlin.'),
        ])
        expect(items.map((i) => i.kind)).toEqual(['bubble', 'internal-group', 'bubble'])
        if (items[1].kind === 'internal-group') {
            // narration (with own tool_calls) + raw `tool` result, both folded away
            expect(items[1].labels).toEqual(['reasoning', 'tool_result'])
        }
    })

    it('hides a raw `tool`-role result message (fix B)', () => {
        const items = buildStreamItems([
            userText('Look up the order'),
            toolRole('paid'),
            assistant('Your order is paid.'),
        ])
        expect(items.map((i) => i.kind)).toEqual(['bubble', 'internal-group', 'bubble'])
        if (items[1].kind === 'internal-group') {
            expect(items[1].labels).toEqual(['tool_result'])
        }
    })

    it('drops a tool-call-only assistant message but collapses its narration sibling', () => {
        // Anthropic split of [text, tool_use]: the empty tool_call message is dropped, the narration
        // text is collapsed because it is followed by the tool result.
        const items = buildStreamItems([
            userText('Build a funnel'),
            assistant('Looking up the schema first.'),
            toolCall('read_taxonomy'),
            toolResult('events: ...'),
            assistant("Here's your funnel."),
        ])
        expect(items.map((i) => i.kind)).toEqual(['bubble', 'internal-group', 'bubble'])
        if (items[1].kind === 'internal-group') {
            expect(items[1].labels).toEqual(['reasoning', 'tool_result'])
        }
    })

    it('does NOT collapse a final answer that has no trailing tool activity', () => {
        const items = buildStreamItems([userText('What is 2+2?'), assistant('4')])
        expect(items.map((i) => i.kind)).toEqual(['bubble', 'bubble'])
    })

    it('does NOT collapse a multi-message final answer (two assistant texts, no tools between)', () => {
        const items = buildStreamItems([
            userText('Summarize and then give next steps'),
            assistant('Summary: things are good.'),
            assistant('Next steps: keep going.'),
        ])
        expect(items.map((i) => i.kind)).toEqual(['bubble', 'bubble', 'bubble'])
    })
})

describe('captureUnrenderableMessageOnce', () => {
    const imageMessage = (url: string): CompatMessage => ({
        role: 'user',
        content: [{ type: 'image_url', image_url: { url } }] as unknown as CompatMessage['content'],
    })

    it('fires the capture with role and content_kinds', () => {
        const seen = new Set<string>()
        captureUnrenderableMessageOnce(imageMessage('a'), seen)
        expect(mockedCapture).toHaveBeenCalledTimes(1)
        expect(mockedCapture).toHaveBeenCalledWith(
            'llma transcript message unrenderable',
            expect.objectContaining({ role: 'user', content_kinds: ['image_url'] })
        )
    })

    it('dedups repeat calls with an identical message', () => {
        const seen = new Set<string>()
        const msg = imageMessage('a')
        captureUnrenderableMessageOnce(msg, seen)
        captureUnrenderableMessageOnce(msg, seen)
        captureUnrenderableMessageOnce(msg, seen)
        expect(mockedCapture).toHaveBeenCalledTimes(1)
    })

    it('fires again for a different image URL even though the role and text are identical', () => {
        const seen = new Set<string>()
        captureUnrenderableMessageOnce(imageMessage('a'), seen)
        captureUnrenderableMessageOnce(imageMessage('b'), seen)
        expect(mockedCapture).toHaveBeenCalledTimes(2)
    })
})
