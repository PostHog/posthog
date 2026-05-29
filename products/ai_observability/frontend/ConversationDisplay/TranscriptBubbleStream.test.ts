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

describe('buildStreamItems — scaffold detection + grouping', () => {
    const userText = (text: string): CompatMessage => ({ role: 'user', content: text })
    const userTypedScaffold = (text: string): CompatMessage => ({
        role: 'user',
        content: [{ type: 'text', text }] as unknown as CompatMessage['content'],
    })
    const assistant = (text: string): CompatMessage => ({ role: 'assistant', content: text })

    it('returns plain bubbles for a non-scaffold conversation', () => {
        const items = buildStreamItems([userText('Hi there'), assistant('Hello')])
        expect(items.map((i) => i.kind)).toEqual(['bubble', 'bubble'])
    })

    it('groups a single scaffold-only user message into a one-pill group', () => {
        const items = buildStreamItems([userText('<system_reminder>foo</system_reminder>')])
        expect(items).toHaveLength(1)
        expect(items[0].kind).toBe('scaffold-group')
        if (items[0].kind === 'scaffold-group') {
            expect(items[0].tagNames).toEqual(['system_reminder'])
            expect(items[0].messages).toHaveLength(1)
        }
    })

    it('groups consecutive scaffold messages into a single pill', () => {
        // Four scaffold messages, then the user's real question.
        const items = buildStreamItems([
            userTypedScaffold('<system_reminder>foo</system_reminder>'),
            userTypedScaffold('<system_reminder>\nbar\n</system_reminder>'),
            userTypedScaffold('<voice_mode>off</voice_mode>'),
            userTypedScaffold('<attached_context>\nbaz\n</attached_context>'),
            userText('what changed?'),
            assistant('looking into it...'),
        ])
        expect(items.map((i) => i.kind)).toEqual(['scaffold-group', 'bubble', 'bubble'])
        if (items[0].kind === 'scaffold-group') {
            expect(items[0].messages).toHaveLength(4)
            expect(items[0].tagNames).toEqual(['system_reminder', 'system_reminder', 'voice_mode', 'attached_context'])
        }
        if (items[1].kind === 'bubble') {
            expect(items[1].text).toBe('what changed?')
        }
    })

    it('breaks grouping when a bubble interrupts the scaffold run', () => {
        // [scaffold, bubble, scaffold] should produce TWO groups, not one — the
        // pill marks chronological position, not "all scaffolds ever".
        const items = buildStreamItems([
            userText('<system_reminder>a</system_reminder>'),
            userText('first question'),
            userText('<voice_mode>off</voice_mode>'),
            assistant('reply'),
        ])
        expect(items.map((i) => i.kind)).toEqual(['scaffold-group', 'bubble', 'scaffold-group', 'bubble'])
    })

    it('does not classify an assistant-role wrapper as scaffold (models can emit `<system_reminder>` in output)', () => {
        const items = buildStreamItems([
            userText('hi'),
            // Unusual but legal: an assistant reply that contains a scaffold-looking wrapper. Render it.
            { role: 'assistant', content: '<system_reminder>foo</system_reminder>' },
        ])
        expect(items.map((i) => i.kind)).toEqual(['bubble', 'bubble'])
    })

    it('does not classify a wrapper-plus-extra-text user message as scaffold', () => {
        // User wrote actual text — we'd lose information by hiding it.
        const items = buildStreamItems([userText('foo <system_reminder>bar</system_reminder> baz')])
        expect(items.map((i) => i.kind)).toEqual(['bubble'])
    })

    it('does not classify unrelated wrapper tags as scaffold', () => {
        // `<thinking>` and friends are not in the allowlist — models can emit them as visible content.
        const items = buildStreamItems([
            userText('<thinking>foo</thinking>'),
            userText('<useful-context>foo</useful-context>'),
            userText('<answer>42</answer>'),
        ])
        expect(items.map((i) => i.kind)).toEqual(['bubble', 'bubble', 'bubble'])
    })

    it('drops `system`-role messages entirely (HIDDEN_ROLES) before scaffold classification', () => {
        const items = buildStreamItems([{ role: 'system', content: 'You are an assistant.' }, userText('hello')])
        expect(items.map((i) => i.kind)).toEqual(['bubble'])
    })

    it('keeps a single scaffold sandwiched between bubbles intact (no merging across bubbles)', () => {
        const items = buildStreamItems([
            userText('first'),
            userText('<system_reminder>x</system_reminder>'),
            assistant('reply'),
        ])
        expect(items.map((i) => i.kind)).toEqual(['bubble', 'scaffold-group', 'bubble'])
        if (items[1].kind === 'scaffold-group') {
            expect(items[1].messages).toHaveLength(1)
        }
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
