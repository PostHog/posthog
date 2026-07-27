import { messageSignature } from './messageSignature'
import { CompatMessage } from './types'

describe('messageSignature', () => {
    it('produces the same signature for messages with identical role + content', () => {
        const a: CompatMessage = { role: 'user', content: 'Hi there' }
        const b: CompatMessage = { role: 'user', content: 'Hi there' }
        expect(messageSignature(a)).toEqual(messageSignature(b))
    })

    const distinctCases: { name: string; a: CompatMessage; b: CompatMessage }[] = [
        {
            name: 'role',
            a: { role: 'user', content: 'same' },
            b: { role: 'assistant', content: 'same' },
        },
        {
            name: 'content for typed-parts arrays',
            a: { role: 'user', content: [{ type: 'text', text: 'Hello' }] },
            b: { role: 'user', content: [{ type: 'text', text: 'Goodbye' }] },
        },
        {
            name: 'tool_calls so assistants with different tool calls are distinct',
            a: {
                role: 'assistant',
                content: '',
                tool_calls: [{ id: '1', type: 'function', function: { name: 'lookup', arguments: '{"q":"a"}' } }],
            },
            b: {
                role: 'assistant',
                content: '',
                tool_calls: [{ id: '1', type: 'function', function: { name: 'lookup', arguments: '{"q":"b"}' } }],
            },
        },
        {
            name: 'tool_call_id for tool responses with the same content',
            a: { role: 'tool', content: 'ok', tool_call_id: 'call_a' },
            b: { role: 'tool', content: 'ok', tool_call_id: 'call_b' },
        },
        {
            // Pins attachment-aware dedup: same text, different image URL must
            // produce different signatures so the second image isn't silently
            // collapsed into the first.
            name: 'image URLs in mixed text+image content',
            a: {
                role: 'user',
                content: [
                    { type: 'text', text: 'Look at this' },
                    { type: 'image_url', image_url: { url: 'https://example.com/a.png' } },
                ],
            },
            b: {
                role: 'user',
                content: [
                    { type: 'text', text: 'Look at this' },
                    { type: 'image_url', image_url: { url: 'https://example.com/b.png' } },
                ],
            },
        },
    ]

    it.each(distinctCases)('distinguishes by $name', ({ a, b }) => {
        expect(messageSignature(a)).not.toEqual(messageSignature(b))
    })
})

describe('messageSignature — transport-metadata stripping', () => {
    // The transport-metadata test cases below use content-part fields that
    // intentionally exceed the strict `CompatMessage` content shapes (Anthropic's
    // `cache_control` / `signature` / `caller` aren't modelled by `TextContentItem`
    // or friends). The `as unknown as CompatMessage` casts say "this is shaped
    // like production payloads we want to pin behavior against, not like the
    // SDK-spec types we ship in `types.ts`".
    const dedupCases: { name: string; a: CompatMessage; b: CompatMessage }[] = [
        {
            // Common Anthropic pattern: a caller stabilises the prefix once it's
            // safe to cache, so turn N+1 has cache_control where turn N didn't.
            // The user-visible text is identical; we must dedup, otherwise the
            // transcript leaks unrendered duplicates back in.
            name: 'Anthropic typed-parts when one turn adds cache_control and another does not',
            a: {
                role: 'system',
                content: [{ type: 'text', text: 'Hello' }],
            } as unknown as CompatMessage,
            b: {
                role: 'system',
                content: [{ type: 'text', text: 'Hello', cache_control: { type: 'ephemeral' } }],
            } as unknown as CompatMessage,
        },
        {
            // Same text, different cache hint. Transport-only change; still the
            // same user-visible content.
            name: 'Anthropic typed-parts when the cache_control hint changes between turns',
            a: {
                role: 'system',
                content: [{ type: 'text', text: 'Hello', cache_control: { type: 'ephemeral' } }],
            } as unknown as CompatMessage,
            b: {
                role: 'system',
                content: [{ type: 'text', text: 'Hello', cache_control: { type: 'ephemeral', ttl: '1h' } }],
            } as unknown as CompatMessage,
        },
        {
            // `signature` is Anthropic's verification crypto on thinking parts —
            // not user-visible and observed to vary between echoes of the same
            // reasoning step in production traces.
            name: 'Anthropic thinking parts even when the cryptographic signature differs',
            a: {
                role: 'assistant',
                content: [{ type: 'thinking', thinking: 'I should look this up.' }],
            } as unknown as CompatMessage,
            b: {
                role: 'assistant',
                content: [{ type: 'thinking', thinking: 'I should look this up.', signature: 'crypto_sig_xyz' }],
            } as unknown as CompatMessage,
        },
        {
            // `caller` is routing metadata observed on tool_use parts in
            // production — not user-visible.
            name: 'tool_use parts even when the caller routing metadata differs',
            a: {
                role: 'assistant',
                content: [{ type: 'tool_use', id: 'toolu_1', name: 'lookup', input: { q: 'cats' } }],
            } as unknown as CompatMessage,
            b: {
                role: 'assistant',
                content: [
                    {
                        type: 'tool_use',
                        id: 'toolu_1',
                        name: 'lookup',
                        input: { q: 'cats' },
                        caller: { type: 'direct' },
                    },
                ],
            } as unknown as CompatMessage,
        },
        {
            // Observed in production: OpenAI tool responses sometimes ship without
            // tool_call_id. Two such responses with the same content are
            // indistinguishable from each other in `$ai_input`, and treating them
            // as one is the only safe thing to do — there's no other key to
            // disambiguate by.
            name: 'two tool responses with identical content even when tool_call_id is missing',
            a: { role: 'tool', content: 'Memory appended.' },
            b: { role: 'tool', content: 'Memory appended.' },
        },
    ]

    it.each(dedupCases)('dedups $name', ({ a, b }) => {
        expect(messageSignature(a)).toEqual(messageSignature(b))
    })

    it('OpenAI tool_calls with the same name but different JSON-string arguments produce distinct signatures', () => {
        const a: CompatMessage = {
            role: 'assistant',
            content: '',
            tool_calls: [
                {
                    function: { name: 'lookup', arguments: '{"q":"first"}' },
                    id: 'call_a',
                    type: 'function',
                },
            ],
        }
        const b: CompatMessage = {
            role: 'assistant',
            content: '',
            tool_calls: [
                {
                    function: { name: 'lookup', arguments: '{"q":"second"}' },
                    id: 'call_a',
                    type: 'function',
                },
            ],
        }
        expect(messageSignature(a)).not.toEqual(messageSignature(b))
    })
})
