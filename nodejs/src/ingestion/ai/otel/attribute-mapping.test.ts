import { PluginEvent } from '~/plugin-scaffold'

import { parseJSON } from '../../../utils/json-parse'
import { extractToolCallNames } from '../tools/extract-tool-calls'
import { mapOtelAttributes } from './attribute-mapping'
import { convertOtelEvent } from './index'

const createEvent = (event: string, properties: Record<string, unknown>): PluginEvent => ({
    event,
    distinct_id: 'user-123',
    team_id: 1,
    properties,
    uuid: 'test-uuid',
    timestamp: new Date().toISOString(),
    ip: '127.0.0.1',
    site_url: 'https://app.posthog.com',
    now: new Date().toISOString(),
})

describe('mapOtelAttributes', () => {
    it.each([
        ['gen_ai.input.messages', '$ai_input'],
        ['gen_ai.output.messages', '$ai_output_choices'],
        ['gen_ai.usage.input_tokens', '$ai_input_tokens'],
        ['gen_ai.usage.output_tokens', '$ai_output_tokens'],
        ['gen_ai.response.model', '$ai_model'],
        ['gen_ai.provider.name', '$ai_provider'],
        ['server.address', '$ai_base_url'],
        ['telemetry.sdk.name', '$ai_lib'],
        ['telemetry.sdk.version', '$ai_lib_version'],
        ['$otel_span_name', '$ai_span_name'],
    ])('renames %s to %s', (otelKey, phKey) => {
        const event = createEvent('$ai_generation', { [otelKey]: 'test-value' })
        mapOtelAttributes(event)
        expect(event.properties![phKey]).toBe('test-value')
        expect(event.properties![otelKey]).toBeUndefined()
    })

    it('JSON-parses string values for $ai_input and $ai_output_choices', () => {
        const event = createEvent('$ai_generation', {
            'gen_ai.input.messages': '[{"role": "user", "content": "Hello"}]',
            'gen_ai.output.messages': '[{"role": "assistant", "content": "Hi"}]',
        })
        mapOtelAttributes(event)
        expect(event.properties!.$ai_input).toEqual([{ role: 'user', content: 'Hello' }])
        expect(event.properties!.$ai_output_choices).toEqual([{ role: 'assistant', content: 'Hi' }])
    })

    it('keeps original string when JSON parsing fails', () => {
        const event = createEvent('$ai_generation', {
            'gen_ai.input.messages': 'not valid json',
        })
        mapOtelAttributes(event)
        expect(event.properties!.$ai_input).toBe('not valid json')
    })

    it('does not JSON-parse already-parsed objects', () => {
        const parsed = [{ role: 'user', content: 'Hello' }]
        const event = createEvent('$ai_generation', {
            'gen_ai.input.messages': parsed,
        })
        mapOtelAttributes(event)
        expect(event.properties!.$ai_input).toEqual(parsed)
    })

    it('preserves unknown attributes', () => {
        const event = createEvent('$ai_generation', {
            'custom.attribute': 'custom-value',
            'gen_ai.response.model': 'gpt-4',
        })
        mapOtelAttributes(event)
        expect(event.properties!['custom.attribute']).toBe('custom-value')
        expect(event.properties!.$ai_model).toBe('gpt-4')
    })

    it.each([
        ['chat', '$ai_generation'],
        ['completion', '$ai_generation'],
        ['embedding', '$ai_embedding'],
        ['embeddings', '$ai_embedding'],
    ])('reclassifies $ai_span to %s when llm.request.type is "%s"', (requestType, expectedEvent) => {
        const event = createEvent('$ai_span', { 'llm.request.type': requestType })
        mapOtelAttributes(event)
        expect(event.event).toBe(expectedEvent)
    })

    it.each(['unknown', 'rerank', ''])('keeps $ai_span when llm.request.type is "%s"', (requestType) => {
        const event = createEvent('$ai_span', { 'llm.request.type': requestType, $ai_parent_id: 'parent-1' })
        mapOtelAttributes(event)
        expect(event.event).toBe('$ai_span')
    })

    it('does not reclassify already-classified events', () => {
        const event = createEvent('$ai_generation', { 'llm.request.type': 'embedding' })
        mapOtelAttributes(event)
        expect(event.event).toBe('$ai_generation')
    })

    it('does not promote reclassified root $ai_generation to $ai_trace', () => {
        const event = createEvent('$ai_span', { 'llm.request.type': 'chat' })
        mapOtelAttributes(event)
        expect(event.event).toBe('$ai_generation')
    })

    it('strips llm.request.type after processing', () => {
        const event = createEvent('$ai_span', { 'llm.request.type': 'chat' })
        mapOtelAttributes(event)
        expect(event.properties!['llm.request.type']).toBeUndefined()
    })

    it.each([
        ['gen_ai.usage.prompt_tokens', '$ai_input_tokens', 150],
        ['gen_ai.usage.completion_tokens', '$ai_output_tokens', 50],
    ])('uses deprecated %s as fallback for %s', (otelKey, phKey, value) => {
        const event = createEvent('$ai_generation', { [otelKey]: value })
        mapOtelAttributes(event)
        expect(event.properties![phKey]).toBe(value)
        expect(event.properties![otelKey]).toBeUndefined()
    })

    it.each([
        ['gen_ai.usage.prompt_tokens', '$ai_input_tokens', 'gen_ai.usage.input_tokens'],
        ['gen_ai.usage.completion_tokens', '$ai_output_tokens', 'gen_ai.usage.output_tokens'],
    ])('does not override %s when primary %s mapping exists', (fallbackKey, phKey, primaryKey) => {
        const event = createEvent('$ai_generation', { [primaryKey]: 100, [fallbackKey]: 200 })
        mapOtelAttributes(event)
        expect(event.properties![phKey]).toBe(100)
        expect(event.properties![fallbackKey]).toBeUndefined()
    })

    it.each([
        ['gen_ai.system', '$ai_provider', 'openai'],
        ['gen_ai.request.model', '$ai_model', 'gpt-4'],
    ])('uses %s as fallback for %s', (otelKey, phKey, value) => {
        const event = createEvent('$ai_generation', { [otelKey]: value })
        mapOtelAttributes(event)
        expect(event.properties![phKey]).toBe(value)
        expect(event.properties![otelKey]).toBeUndefined()
    })

    it.each([
        ['gen_ai.system', '$ai_provider', 'gen_ai.provider.name'],
        ['gen_ai.request.model', '$ai_model', 'gen_ai.response.model'],
    ])('does not override %s when primary mapping for %s exists', (fallbackKey, phKey, primaryKey) => {
        const event = createEvent('$ai_generation', { [primaryKey]: 'primary', [fallbackKey]: 'fallback' })
        mapOtelAttributes(event)
        expect(event.properties![phKey]).toBe('primary')
        expect(event.properties![fallbackKey]).toBeUndefined()
    })

    it('prefers gen_ai.response.model over gen_ai.request.model', () => {
        const event = createEvent('$ai_generation', {
            'gen_ai.request.model': 'gpt-4o-mini',
            'gen_ai.response.model': 'gpt-4o-mini-2024-07-18',
        })
        mapOtelAttributes(event)
        expect(event.properties!.$ai_model).toBe('gpt-4o-mini-2024-07-18')
        expect(event.properties!['gen_ai.request.model']).toBeUndefined()
        expect(event.properties!['gen_ai.response.model']).toBeUndefined()
    })

    it.each(['telemetry.sdk.language', 'gen_ai.operation.name', 'posthog.ai.debug'])(
        'strips %s from properties',
        (key) => {
            const event = createEvent('$ai_generation', { [key]: 'some-value' })
            mapOtelAttributes(event)
            expect(event.properties![key]).toBeUndefined()
        }
    )

    it('computes $ai_latency from OTel timestamps', () => {
        const event = createEvent('$ai_generation', {
            $otel_start_time_unix_nano: '1704067200000000000',
            $otel_end_time_unix_nano: '1704067201500000000',
        })
        mapOtelAttributes(event)
        expect(event.properties!['$ai_latency']).toBe(1.5)
        expect(event.properties!['$otel_start_time_unix_nano']).toBeUndefined()
        expect(event.properties!['$otel_end_time_unix_nano']).toBeUndefined()
    })

    it('does not set $ai_latency when end <= start', () => {
        const event = createEvent('$ai_generation', {
            $otel_start_time_unix_nano: '1000000000000000000',
            $otel_end_time_unix_nano: '0',
        })
        mapOtelAttributes(event)
        expect(event.properties!['$ai_latency']).toBeUndefined()
    })

    it('does not crash on malformed nanosecond timestamps', () => {
        const event = createEvent('$ai_generation', {
            $otel_start_time_unix_nano: 'not-a-number',
            $otel_end_time_unix_nano: 'also-bad',
        })
        mapOtelAttributes(event)
        expect(event.properties!['$ai_latency']).toBeUndefined()
        expect(event.properties!['$otel_start_time_unix_nano']).toBeUndefined()
        expect(event.properties!['$otel_end_time_unix_nano']).toBeUndefined()
    })

    it('strips OTel timestamp properties even when latency cannot be computed', () => {
        const event = createEvent('$ai_generation', {
            $otel_start_time_unix_nano: '1000000000000000000',
            $otel_end_time_unix_nano: '0',
        })
        mapOtelAttributes(event)
        expect(event.properties!['$otel_start_time_unix_nano']).toBeUndefined()
        expect(event.properties!['$otel_end_time_unix_nano']).toBeUndefined()
    })

    it('promotes root $ai_span to $ai_trace', () => {
        const event = createEvent('$ai_span', {
            $otel_start_time_unix_nano: '0',
            $otel_end_time_unix_nano: '0',
        })
        mapOtelAttributes(event)
        expect(event.event).toBe('$ai_trace')
    })

    it('does not promote $ai_span with parent to $ai_trace', () => {
        const event = createEvent('$ai_span', {
            $ai_parent_id: 'abc123',
            $otel_start_time_unix_nano: '0',
            $otel_end_time_unix_nano: '0',
        })
        mapOtelAttributes(event)
        expect(event.event).toBe('$ai_span')
    })

    it('does not promote $ai_generation to $ai_trace', () => {
        const event = createEvent('$ai_generation', {
            $otel_start_time_unix_nano: '0',
            $otel_end_time_unix_nano: '0',
        })
        mapOtelAttributes(event)
        expect(event.event).toBe('$ai_generation')
    })

    describe('older-spec span events (`events` attribute)', () => {
        it('reconstructs $ai_input and $ai_output_choices from span-events-style `events`', () => {
            const events = [
                {
                    role: 'system',
                    content: 'Extract city information.',
                    'gen_ai.message.index': 0,
                    'event.name': 'gen_ai.system.message',
                },
                {
                    role: 'user',
                    content: 'Tell me about Montreal, Canada.',
                    'gen_ai.message.index': 0,
                    'event.name': 'gen_ai.user.message',
                },
                {
                    index: 0,
                    message: {
                        role: 'assistant',
                        content: 'Montreal is a city in Canada.',
                    },
                    'event.name': 'gen_ai.choice',
                },
            ]
            const event = createEvent('$ai_generation', { events: JSON.stringify(events) })
            mapOtelAttributes(event)

            expect(event.properties!.$ai_input).toEqual([
                { role: 'system', content: 'Extract city information.' },
                { role: 'user', content: 'Tell me about Montreal, Canada.' },
            ])
            expect(event.properties!.$ai_output_choices).toEqual([
                { role: 'assistant', content: 'Montreal is a city in Canada.' },
            ])
            expect(event.properties!.events).toBeUndefined()
        })

        it('orders $ai_input by gen_ai.message.index when all entries have one', () => {
            const events = [
                { role: 'assistant', 'gen_ai.message.index': 2, 'event.name': 'gen_ai.assistant.message' },
                { role: 'user', 'gen_ai.message.index': 1, 'event.name': 'gen_ai.user.message' },
                { role: 'system', 'gen_ai.message.index': 0, 'event.name': 'gen_ai.system.message' },
            ]
            const event = createEvent('$ai_generation', { events: JSON.stringify(events) })
            mapOtelAttributes(event)

            expect(event.properties!.$ai_input).toEqual([{ role: 'system' }, { role: 'user' }, { role: 'assistant' }])
        })

        it('preserves array order when entries lack gen_ai.message.index', () => {
            const events = [
                { role: 'system', content: 'S', 'event.name': 'gen_ai.system.message' },
                { role: 'user', content: 'U', 'event.name': 'gen_ai.user.message' },
            ]
            const event = createEvent('$ai_generation', { events: JSON.stringify(events) })
            mapOtelAttributes(event)

            expect(event.properties!.$ai_input).toEqual([
                { role: 'system', content: 'S' },
                { role: 'user', content: 'U' },
            ])
        })

        it('prefers newer gen_ai.input.messages over older `events` but still strips `events`', () => {
            const newer = [{ role: 'user', content: 'newer' }]
            const older = [{ role: 'user', content: 'older', 'event.name': 'gen_ai.user.message' }]
            const event = createEvent('$ai_generation', {
                'gen_ai.input.messages': JSON.stringify(newer),
                events: JSON.stringify(older),
            })
            mapOtelAttributes(event)

            expect(event.properties!.$ai_input).toEqual(newer)
            expect(event.properties!.events).toBeUndefined()
        })

        it('produces $ai_output_choices that downstream tool extraction can read', () => {
            const events = [
                {
                    index: 0,
                    message: {
                        role: 'assistant',
                        tool_calls: [
                            {
                                id: 'call_abc',
                                type: 'function',
                                function: { name: 'final_result', arguments: '{}' },
                            },
                            {
                                id: 'call_def',
                                type: 'function',
                                function: { name: 'get_weather', arguments: '{}' },
                            },
                        ],
                    },
                    'event.name': 'gen_ai.choice',
                },
            ]
            const event = createEvent('$ai_generation', { events: JSON.stringify(events) })
            mapOtelAttributes(event)

            expect(extractToolCallNames(event.properties!.$ai_output_choices)).toEqual(['final_result', 'get_weather'])
        })

        it.each([
            ['gen_ai.system.message', 'system'],
            ['gen_ai.user.message', 'user'],
            ['gen_ai.assistant.message', 'assistant'],
            ['gen_ai.tool.message', 'tool'],
        ])('infers role "%s" → "%s" when the entry has no explicit role', (eventName, expectedRole) => {
            const events = [{ content: 'body', 'event.name': eventName }]
            const event = createEvent('$ai_generation', { events: JSON.stringify(events) })
            mapOtelAttributes(event)

            expect(event.properties!.$ai_input).toEqual([{ role: expectedRole, content: 'body' }])
        })

        it('does not throw on malformed `events` JSON and still strips the property', () => {
            const event = createEvent('$ai_generation', { events: 'not { valid json' })
            mapOtelAttributes(event)

            expect(event.properties!.$ai_input).toBeUndefined()
            expect(event.properties!.$ai_output_choices).toBeUndefined()
            expect(event.properties!.events).toBeUndefined()
        })

        it('does not throw when `events` parses to a non-array and still strips the property', () => {
            const event = createEvent('$ai_generation', { events: JSON.stringify({ foo: 1 }) })
            mapOtelAttributes(event)

            expect(event.properties!.$ai_input).toBeUndefined()
            expect(event.properties!.$ai_output_choices).toBeUndefined()
            expect(event.properties!.events).toBeUndefined()
        })

        it('accepts `events` as an already-parsed array', () => {
            const events = [
                { role: 'user', content: 'hi', 'event.name': 'gen_ai.user.message' },
                { index: 0, message: { role: 'assistant', content: 'hello' }, 'event.name': 'gen_ai.choice' },
            ]
            const event = createEvent('$ai_generation', { events })
            mapOtelAttributes(event)

            expect(event.properties!.$ai_input).toEqual([{ role: 'user', content: 'hi' }])
            expect(event.properties!.$ai_output_choices).toEqual([{ role: 'assistant', content: 'hello' }])
            expect(event.properties!.events).toBeUndefined()
        })

        it('ignores entries with unknown event.name but reconstructs recognised ones', () => {
            const events = [
                { role: 'user', content: 'hi', 'event.name': 'gen_ai.user.message' },
                { role: 'spurious', 'event.name': 'gen_ai.unknown.thing' },
                { index: 0, message: { role: 'assistant', content: 'hello' }, 'event.name': 'gen_ai.choice' },
            ]
            const event = createEvent('$ai_generation', { events: JSON.stringify(events) })
            mapOtelAttributes(event)

            expect(event.properties!.$ai_input).toEqual([{ role: 'user', content: 'hi' }])
            expect(event.properties!.$ai_output_choices).toEqual([{ role: 'assistant', content: 'hello' }])
        })

        it('preserves array order when only some entries have gen_ai.message.index', () => {
            const events = [
                { role: 'system', content: 'S', 'gen_ai.message.index': 5, 'event.name': 'gen_ai.system.message' },
                { role: 'user', content: 'U', 'event.name': 'gen_ai.user.message' },
                {
                    role: 'assistant',
                    content: 'A',
                    'gen_ai.message.index': 0,
                    'event.name': 'gen_ai.assistant.message',
                },
            ]
            const event = createEvent('$ai_generation', { events: JSON.stringify(events) })
            mapOtelAttributes(event)

            expect(event.properties!.$ai_input).toEqual([
                { role: 'system', content: 'S' },
                { role: 'user', content: 'U' },
                { role: 'assistant', content: 'A' },
            ])
        })

        it('preserves tool_calls on gen_ai.assistant.message entries in $ai_input', () => {
            const toolCalls = [
                { id: 'call_1', type: 'function', function: { name: 'search', arguments: '{"q":"paris"}' } },
            ]
            const events = [
                { role: 'user', content: 'find paris', 'event.name': 'gen_ai.user.message' },
                { role: 'assistant', tool_calls: toolCalls, 'event.name': 'gen_ai.assistant.message' },
                {
                    role: 'tool',
                    content: 'ok',
                    tool_call_id: 'call_1',
                    'event.name': 'gen_ai.tool.message',
                },
            ]
            const event = createEvent('$ai_generation', { events: JSON.stringify(events) })
            mapOtelAttributes(event)

            expect(event.properties!.$ai_input).toEqual([
                { role: 'user', content: 'find paris' },
                { role: 'assistant', tool_calls: toolCalls },
                { role: 'tool', content: 'ok', tool_call_id: 'call_1' },
            ])
        })

        it('treats pre-existing null $ai_input as already set and does not overwrite', () => {
            const events = [{ role: 'user', content: 'hi', 'event.name': 'gen_ai.user.message' }]
            const event = createEvent('$ai_generation', { $ai_input: null, events: JSON.stringify(events) })
            mapOtelAttributes(event)

            expect(event.properties!.$ai_input).toBeNull()
            expect(event.properties!.events).toBeUndefined()
        })

        it('does not mutate $ai_output_choices by reference into the parsed events payload', () => {
            const events = [
                {
                    message: { role: 'assistant', content: 'original' },
                    'event.name': 'gen_ai.choice',
                },
            ]
            const eventsString = JSON.stringify(events)
            const event = createEvent('$ai_generation', { events: eventsString })
            mapOtelAttributes(event)

            // Mutating the emitted choice must not affect any shared transient
            // structure — we shallow-copy the inner message in reconstructOutputChoice.
            const choices = event.properties!.$ai_output_choices as Record<string, unknown>[]
            ;(choices[0] as Record<string, unknown>).content = 'mutated'
            // Re-parse the original events string to confirm nothing leaked back.
            const reparsed = parseJSON(eventsString) as { message: { content: string } }[]
            expect(reparsed[0].message.content).toBe('original')
        })

        it('skips parsing when `events` string exceeds the size guard and still strips it', () => {
            const oversized = 'x'.repeat(500_001)
            const event = createEvent('$ai_generation', { events: oversized })
            mapOtelAttributes(event)

            expect(event.properties!.$ai_input).toBeUndefined()
            expect(event.properties!.$ai_output_choices).toBeUndefined()
            expect(event.properties!.events).toBeUndefined()
        })
    })

    describe('older-spec span events composed with pydantic-ai middleware', () => {
        it('reconstructs $ai_input/$ai_output_choices alongside pydantic-ai framework attributes', () => {
            // Realistic runtime path: pydantic-ai middleware runs, calls
            // `next()` which invokes `mapOtelAttributes` (and therefore our
            // `convertOlderSpecEvents` fallback), then the middleware applies
            // its own post-processing.
            const olderEvents = [
                { role: 'user', content: 'Hello', 'event.name': 'gen_ai.user.message' },
                {
                    message: { role: 'assistant', content: 'Hi there!' },
                    'event.name': 'gen_ai.choice',
                },
            ]
            const event = createEvent('$ai_span', {
                $ai_ingestion_source: 'otel',
                'telemetry.sdk.name': 'opentelemetry',
                'logfire.msg': 'chat gpt-4o-mini',
                'llm.request.type': 'chat',
                'gen_ai.response.model': 'gpt-4o-mini-2024-07-18',
                events: JSON.stringify(olderEvents),
            })

            convertOtelEvent(event)

            expect(event.event).toBe('$ai_generation')
            expect(event.properties!.$ai_lib).toBe('opentelemetry/pydantic-ai')
            expect(event.properties!.$ai_span_name).toBe('chat gpt-4o-mini')
            expect(event.properties!.$ai_model).toBe('gpt-4o-mini-2024-07-18')
            expect(event.properties!.$ai_input).toEqual([{ role: 'user', content: 'Hello' }])
            expect(event.properties!.$ai_output_choices).toEqual([{ role: 'assistant', content: 'Hi there!' }])
            expect(event.properties!.events).toBeUndefined()
        })
    })
})
