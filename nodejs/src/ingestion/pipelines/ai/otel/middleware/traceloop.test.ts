import { mapOtelAttributes } from '~/ingestion/pipelines/ai/otel/attribute-mapping'
import { createEvent } from '~/ingestion/pipelines/ai/otel/test-helpers'

import { reassembleIndexedAttributes, traceloop } from './traceloop'

jest.mock('~/ingestion/pipelines/ai/otel/attribute-mapping', () => ({
    mapOtelAttributes: jest.fn(),
}))

const mockedMapOtelAttributes = jest.mocked(mapOtelAttributes)

describe('traceloop middleware', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    describe('matches', () => {
        it.each([
            ['llm.request.type', { 'llm.request.type': 'chat' }],
            ['traceloop.span.kind', { 'traceloop.span.kind': 'workflow' }],
            ['traceloop.entity.name', { 'traceloop.entity.name': 'openai.chat' }],
        ])('detects traceloop from %s', (_label, properties) => {
            const event = createEvent('$ai_span', properties)
            expect(traceloop.matches(event)).toBe(true)
        })

        it.each([
            ['no markers', {}],
            ['only gen_ai.system', { 'gen_ai.system': 'openai' }],
        ])('does not match when %s', (_label, properties) => {
            const event = createEvent('$ai_generation', properties)
            expect(traceloop.matches(event)).toBe(false)
        })
    })

    describe('reassembleIndexedAttributes', () => {
        it('reassembles gen_ai.prompt.* into structured messages', () => {
            const props: Record<string, unknown> = {
                'gen_ai.prompt.0.role': 'system',
                'gen_ai.prompt.0.content': 'You are helpful',
                'gen_ai.prompt.1.role': 'user',
                'gen_ai.prompt.1.content': 'Hello',
            }
            const result = reassembleIndexedAttributes(
                props,
                'gen_ai.prompt.',
                ['role', 'content', 'tool_call_id'],
                ['tool_calls']
            )

            expect(result).toEqual([
                { role: 'system', content: 'You are helpful' },
                { role: 'user', content: 'Hello' },
            ])
            expect(props['gen_ai.prompt.0.role']).toBeUndefined()
        })

        it('handles nested groups like tool_calls', () => {
            const props: Record<string, unknown> = {
                'gen_ai.prompt.0.role': 'assistant',
                'gen_ai.prompt.0.content': '',
                'gen_ai.prompt.0.tool_calls.0.name': 'get_weather',
                'gen_ai.prompt.0.tool_calls.0.arguments': '{"city":"NYC"}',
                'gen_ai.prompt.0.tool_calls.1.name': 'get_time',
                'gen_ai.prompt.0.tool_calls.1.arguments': '{"tz":"EST"}',
                'gen_ai.prompt.1.role': 'tool',
                'gen_ai.prompt.1.content': 'Sunny, 72F',
                'gen_ai.prompt.1.tool_call_id': 'call-123',
            }
            const result = reassembleIndexedAttributes(
                props,
                'gen_ai.prompt.',
                ['role', 'content', 'tool_call_id'],
                ['tool_calls']
            )

            expect(result).toEqual([
                {
                    role: 'assistant',
                    content: '',
                    tool_calls: [
                        { name: 'get_weather', arguments: '{"city":"NYC"}' },
                        { name: 'get_time', arguments: '{"tz":"EST"}' },
                    ],
                },
                { role: 'tool', content: 'Sunny, 72F', tool_call_id: 'call-123' },
            ])
        })

        it('handles non-contiguous indices', () => {
            const props: Record<string, unknown> = {
                'gen_ai.prompt.0.role': 'user',
                'gen_ai.prompt.0.content': 'First',
                'gen_ai.prompt.5.role': 'assistant',
                'gen_ai.prompt.5.content': 'Second',
            }
            const result = reassembleIndexedAttributes(props, 'gen_ai.prompt.', ['role', 'content'], [])

            expect(result).toEqual([
                { role: 'user', content: 'First' },
                { role: 'assistant', content: 'Second' },
            ])
        })

        it('returns undefined when no matching prefix keys exist', () => {
            const props: Record<string, unknown> = { 'some.other.key': 'value' }
            const result = reassembleIndexedAttributes(props, 'gen_ai.prompt.', ['role', 'content'], [])
            expect(result).toBeUndefined()
        })

        it('returns undefined when keys match prefix but no fields are recognized', () => {
            const props: Record<string, unknown> = { 'gen_ai.prompt.0.unknown_field': 'value' }
            const result = reassembleIndexedAttributes(props, 'gen_ai.prompt.', ['role', 'content'], [])
            expect(result).toBeUndefined()
            expect(props['gen_ai.prompt.0.unknown_field']).toBe('value')
        })
    })

    describe('process', () => {
        it('reassembles prompts into $ai_input', () => {
            const event = createEvent('$ai_generation', {
                'llm.request.type': 'chat',
                'gen_ai.prompt.0.role': 'user',
                'gen_ai.prompt.0.content': 'Hello',
            })
            traceloop.process(event, () => mapOtelAttributes(event))

            expect(event.properties!['$ai_input']).toEqual([{ role: 'user', content: 'Hello' }])
        })

        it('maps the Go SDK llm.* key variants (messages, model, tokens, vendor)', () => {
            // go-openllmetry emits llm.prompts/llm.completions/llm.usage.*
            // where the Python SDK emits gen_ai.* — a span from the Go SDK
            // must not land stripped down to latency only.
            const event = createEvent('$ai_generation', {
                'llm.request.type': 'chat',
                'llm.vendor': 'anthropic',
                'llm.request.model': 'claude-haiku-4-5',
                'llm.response.model': 'claude-haiku-4-5-20251001',
                'llm.usage.prompt_tokens': 20,
                'llm.usage.completion_tokens': 4,
                'llm.prompts.0.role': 'system',
                'llm.prompts.0.content': 'Be terse.',
                'llm.prompts.1.role': 'user',
                'llm.prompts.1.content': 'Capital of France?',
                'llm.completions.0.role': 'assistant',
                'llm.completions.0.content': 'Paris.',
            })
            traceloop.process(event, () => mapOtelAttributes(event))

            const props = event.properties!
            expect(props['$ai_input']).toEqual([
                { role: 'system', content: 'Be terse.' },
                { role: 'user', content: 'Capital of France?' },
            ])
            expect(props['$ai_output_choices']).toEqual([{ role: 'assistant', content: 'Paris.' }])
            expect(props['$ai_model']).toBe('claude-haiku-4-5-20251001')
            expect(props['$ai_provider']).toBe('anthropic')
            expect(props['$ai_input_tokens']).toBe(20)
            expect(props['$ai_output_tokens']).toBe(4)
            expect(props['llm.prompts.0.role']).toBeUndefined()
            expect(props['llm.usage.prompt_tokens']).toBeUndefined()
            expect(props['llm.vendor']).toBeUndefined()
        })

        it('does not let Go SDK fallbacks override values the base mapping set', () => {
            const event = createEvent('$ai_generation', {
                'llm.request.type': 'chat',
                'llm.request.model': 'stale-model',
                $ai_model: 'canonical-model',
            })
            traceloop.process(event, () => mapOtelAttributes(event))

            expect(event.properties!['$ai_model']).toBe('canonical-model')
            expect(event.properties!['llm.request.model']).toBeUndefined()
        })

        it('reassembles completions into $ai_output_choices', () => {
            const event = createEvent('$ai_generation', {
                'llm.request.type': 'chat',
                'gen_ai.completion.0.role': 'assistant',
                'gen_ai.completion.0.content': 'Hi there!',
            })
            traceloop.process(event, () => mapOtelAttributes(event))

            expect(event.properties!['$ai_output_choices']).toEqual([{ role: 'assistant', content: 'Hi there!' }])
        })

        it('reassembles functions into $ai_tools', () => {
            const event = createEvent('$ai_generation', {
                'llm.request.type': 'chat',
                'llm.request.functions.0.name': 'get_weather',
                'llm.request.functions.0.description': 'Get weather for a city',
                'llm.request.functions.0.parameters': '{"type":"object"}',
            })
            traceloop.process(event, () => mapOtelAttributes(event))

            expect(event.properties!['$ai_tools']).toEqual([
                { name: 'get_weather', description: 'Get weather for a city', parameters: '{"type":"object"}' },
            ])
        })

        it('does not override $ai_input when already set by generic mapping', () => {
            mockedMapOtelAttributes.mockImplementation((e) => {
                if (e.properties) {
                    e.properties['$ai_input'] = [{ role: 'user', content: 'from generic' }]
                }
            })
            const event = createEvent('$ai_generation', {
                'llm.request.type': 'chat',
                'gen_ai.prompt.0.role': 'user',
                'gen_ai.prompt.0.content': 'from traceloop',
            })
            traceloop.process(event, () => mapOtelAttributes(event))

            expect(event.properties!['$ai_input']).toEqual([{ role: 'user', content: 'from generic' }])
        })

        it('sets $ai_lib to opentelemetry/traceloop', () => {
            const event = createEvent('$ai_generation', { 'llm.request.type': 'chat' })
            traceloop.process(event, () => mapOtelAttributes(event))
            expect(event.properties!['$ai_lib']).toBe('opentelemetry/traceloop')
        })

        it('strips traceloop-specific keys', () => {
            const event = createEvent('$ai_generation', {
                'llm.request.type': 'chat',
                'traceloop.span.kind': 'workflow',
                'traceloop.entity.name': 'openai.chat',
                'traceloop.entity.path': 'app.main',
                'traceloop.workflow.name': 'my_workflow',
                'traceloop.entity.input': '{}',
                'traceloop.entity.output': '{}',
                'traceloop.association.properties.user_id': '123',
                'traceloop.association.properties.session_id': 'abc',
                'llm.is_streaming': false,
                'llm.usage.total_tokens': 200,
                'llm.response.finish_reason': 'stop',
                'llm.response.stop_reason': 'end_turn',
            })
            traceloop.process(event, () => mapOtelAttributes(event))

            expect(event.properties!['traceloop.span.kind']).toBeUndefined()
            expect(event.properties!['traceloop.entity.name']).toBeUndefined()
            expect(event.properties!['traceloop.entity.path']).toBeUndefined()
            expect(event.properties!['traceloop.workflow.name']).toBeUndefined()
            expect(event.properties!['traceloop.entity.input']).toBeUndefined()
            expect(event.properties!['traceloop.entity.output']).toBeUndefined()
            expect(event.properties!['traceloop.association.properties.user_id']).toBeUndefined()
            expect(event.properties!['traceloop.association.properties.session_id']).toBeUndefined()
            expect(event.properties!['llm.is_streaming']).toBeUndefined()
            expect(event.properties!['llm.usage.total_tokens']).toBeUndefined()
            expect(event.properties!['llm.response.finish_reason']).toBeUndefined()
            expect(event.properties!['llm.response.stop_reason']).toBeUndefined()
            // stop_reason takes priority over finish_reason
            expect(event.properties!['$ai_stop_reason']).toBe('end_turn')
        })

        it('maps finish_reason to $ai_stop_reason when stop_reason is absent', () => {
            const event = createEvent('$ai_generation', {
                'llm.request.type': 'chat',
                'llm.response.finish_reason': 'stop',
            })
            traceloop.process(event, () => mapOtelAttributes(event))

            expect(event.properties!['llm.response.finish_reason']).toBeUndefined()
            expect(event.properties!['$ai_stop_reason']).toBe('stop')
        })

        it('leaves $ai_stop_reason undefined when neither reason is present', () => {
            const event = createEvent('$ai_generation', {
                'llm.request.type': 'chat',
            })
            traceloop.process(event, () => mapOtelAttributes(event))

            expect(event.properties!['$ai_stop_reason']).toBeUndefined()
        })
    })
})
