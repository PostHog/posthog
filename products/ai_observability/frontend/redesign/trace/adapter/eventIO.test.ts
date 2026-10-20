import { LLMTraceEvent } from '~/queries/schema/schema-general'

import { AIData } from '../../../aiObservabilityAIDataLogic'
import { heavyDataLookup, resolveEventIO } from './eventIO'
import { makeEvent } from './testFixtures'

interface ResolveEventIOCase {
    name: string
    event: LLMTraceEvent
    cache: Record<string, AIData | null>
    expected: { input: unknown; output: unknown; loading: boolean }
}

const resolveEventIOCases: ResolveEventIOCase[] = [
    {
        name: 'a generation with inline input and output',
        event: makeEvent({
            id: 'gen-1',
            event: '$ai_generation',
            properties: {
                $ai_input: [{ role: 'user', content: 'Why did my invoice go up?' }],
                $ai_output_choices: [{ role: 'assistant', content: 'Two seats were added.' }],
            },
        }),
        cache: {},
        expected: {
            input: [{ role: 'user', content: 'Why did my invoice go up?' }],
            output: [{ role: 'assistant', content: 'Two seats were added.' }],
            loading: false,
        },
    },
    {
        name: 'a generation missing input, with no cache entry yet',
        event: makeEvent({ id: 'gen-2', event: '$ai_generation', properties: {} }),
        cache: {},
        expected: { input: undefined, output: undefined, loading: true },
    },
    {
        name: 'a generation missing input, with a cache entry that found nothing',
        event: makeEvent({ id: 'gen-3', event: '$ai_generation', properties: {} }),
        cache: { 'gen-3': null },
        expected: { input: undefined, output: undefined, loading: false },
    },
    {
        name: 'a generation missing input, with a loaded cache entry',
        event: makeEvent({ id: 'gen-4', event: '$ai_generation', properties: {} }),
        cache: {
            'gen-4': {
                input: [{ role: 'user', content: 'Cached question' }],
                output: [{ role: 'assistant', content: 'Cached answer' }],
                tools: null,
            },
        },
        expected: {
            input: [{ role: 'user', content: 'Cached question' }],
            output: [{ role: 'assistant', content: 'Cached answer' }],
            loading: false,
        },
    },
    {
        name: 'an embedding',
        event: makeEvent({ id: 'emb-1', event: '$ai_embedding', properties: { $ai_input: 'embed this text' } }),
        cache: {},
        expected: { input: 'embed this text', output: null, loading: false },
    },
    {
        name: 'a span',
        event: makeEvent({
            id: 'span-1',
            event: '$ai_span',
            properties: { $ai_input_state: { step: 1 }, $ai_output_state: { step: 2 } },
        }),
        cache: {},
        expected: { input: { step: 1 }, output: { step: 2 }, loading: false },
    },
    {
        name: 'an OTel span that carries generation-style input and output',
        event: makeEvent({
            id: 'span-2',
            event: '$ai_span',
            properties: {
                $ai_input: [{ role: 'user', content: 'Suggest hashtags' }],
                $ai_output_choices: 'Added #levelup',
            },
        }),
        cache: {},
        expected: { input: [{ role: 'user', content: 'Suggest hashtags' }], output: 'Added #levelup', loading: false },
    },
]

describe('eventIO', () => {
    describe('resolveEventIO', () => {
        it.each(resolveEventIOCases)('$name', ({ event, cache, expected }) => {
            expect(resolveEventIO(event, cache)).toEqual(expected)
        })
    })

    describe('heavyDataLookup', () => {
        it('returns null for a generation with both input and output present', () => {
            const event = makeEvent({
                id: 'gen-1',
                event: '$ai_generation',
                properties: {
                    $ai_input: [{ role: 'user', content: 'Why did my invoice go up?' }],
                    $ai_output_choices: [{ role: 'assistant', content: 'Two seats were added.' }],
                },
            })
            expect(heavyDataLookup(event, 'trace-1')).toBeNull()
        })

        it('returns null for a span', () => {
            const event = makeEvent({
                id: 'span-1',
                event: '$ai_span',
                properties: { $ai_input_state: { step: 1 }, $ai_output_state: { step: 2 } },
            })
            expect(heavyDataLookup(event, 'trace-1')).toBeNull()
        })

        it('returns a lookup for a generation missing output', () => {
            const event = makeEvent({
                id: 'gen-2',
                event: '$ai_generation',
                createdAt: '2026-09-01T10:15:02Z',
                properties: {
                    $ai_input: [{ role: 'user', content: 'Why did my invoice go up?' }],
                    $ai_tools: [{ name: 'lookup_invoice' }],
                },
            })
            expect(heavyDataLookup(event, 'trace-1')).toEqual({
                eventId: 'gen-2',
                input: [{ role: 'user', content: 'Why did my invoice go up?' }],
                output: undefined,
                tools: [{ name: 'lookup_invoice' }],
                traceId: 'trace-1',
                timestamp: '2026-09-01T10:15:02Z',
            })
        })
    })
})
