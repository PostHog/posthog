import { mapOtelAttributes } from '~/ingestion/pipelines/ai/otel/attribute-mapping'
import { createEvent } from '~/ingestion/pipelines/ai/otel/test-helpers'

import { openinference } from './openinference'

jest.mock('~/ingestion/pipelines/ai/otel/attribute-mapping', () => ({
    mapOtelAttributes: jest.fn(),
}))

describe('openinference middleware', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    describe('matches', () => {
        it('detects openinference from the span kind marker', () => {
            const event = createEvent('$ai_generation', { 'openinference.span.kind': 'LLM' })
            expect(openinference.matches(event)).toBe(true)
        })

        it('does not match bare llm.* keys without the marker', () => {
            const event = createEvent('$ai_generation', { 'llm.model_name': 'claude-haiku-4-5' })
            expect(openinference.matches(event)).toBe(false)
        })
    })

    describe('process', () => {
        it('maps a full anthropic-sdk-go LLM span into PostHog properties', () => {
            const event = createEvent('$ai_generation', {
                'openinference.span.kind': 'LLM',
                'llm.system': 'anthropic',
                'llm.provider': 'anthropic',
                'llm.model_name': 'claude-haiku-4-5-20251001',
                'llm.invocation_parameters': '{"max_tokens":100,"temperature":0.5}',
                'llm.token_count.prompt': 20,
                'llm.token_count.completion': 4,
                'llm.token_count.total': 24,
                'llm.finish_reason': 'end_turn',
                'llm.input_messages.0.message.role': 'system',
                'llm.input_messages.0.message.content': 'Be terse.',
                'llm.input_messages.1.message.role': 'user',
                'llm.input_messages.1.message.content': 'Capital of France?',
                'llm.output_messages.0.message.role': 'assistant',
                'llm.output_messages.0.message.content': 'Paris.',
                'input.value': 'Capital of France?',
                'output.value': 'Paris.',
            })
            openinference.process(event, () => mapOtelAttributes(event))

            const props = event.properties!
            expect(props['$ai_model']).toBe('claude-haiku-4-5-20251001')
            expect(props['$ai_provider']).toBe('anthropic')
            expect(props['$ai_input_tokens']).toBe(20)
            expect(props['$ai_output_tokens']).toBe(4)
            expect(props['$ai_stop_reason']).toBe('end_turn')
            expect(props['$ai_model_parameters']).toEqual({ max_tokens: 100, temperature: 0.5 })
            expect(props['$ai_input']).toEqual([
                { role: 'system', content: 'Be terse.' },
                { role: 'user', content: 'Capital of France?' },
            ])
            expect(props['$ai_output_choices']).toEqual([{ role: 'assistant', content: 'Paris.' }])
            expect(props['$ai_lib']).toBe('opentelemetry/openinference')

            expect(props['openinference.span.kind']).toBeUndefined()
            expect(props['llm.model_name']).toBeUndefined()
            expect(props['llm.input_messages.0.message.role']).toBeUndefined()
            expect(props['input.value']).toBeUndefined()
            expect(props['llm.token_count.total']).toBeUndefined()
        })

        it('reassembles output tool calls into OpenAI-shaped tool_calls', () => {
            const event = createEvent('$ai_generation', {
                'openinference.span.kind': 'LLM',
                'llm.output_messages.0.message.role': 'assistant',
                'llm.output_messages.0.message.tool_calls.0.tool_call.id': 'toolu_1',
                'llm.output_messages.0.message.tool_calls.0.tool_call.function.name': 'get_weather',
                'llm.output_messages.0.message.tool_calls.0.tool_call.function.arguments': '{"location":"Paris"}',
            })
            openinference.process(event, () => mapOtelAttributes(event))

            expect(event.properties!['$ai_output_choices']).toEqual([
                {
                    role: 'assistant',
                    tool_calls: [
                        {
                            id: 'toolu_1',
                            type: 'function',
                            function: { name: 'get_weather', arguments: '{"location":"Paris"}' },
                        },
                    ],
                },
            ])
        })

        it('parses llm.tools.*.tool.json_schema into $ai_tools', () => {
            const event = createEvent('$ai_generation', {
                'openinference.span.kind': 'LLM',
                'llm.tools.0.tool.json_schema': '{"name":"get_weather","input_schema":{"type":"object"}}',
            })
            openinference.process(event, () => mapOtelAttributes(event))

            expect(event.properties!['$ai_tools']).toEqual([{ name: 'get_weather', input_schema: { type: 'object' } }])
        })

        it('falls back to input.value / output.value when indexed messages are absent (streaming spans)', () => {
            const event = createEvent('$ai_generation', {
                'openinference.span.kind': 'LLM',
                'input.value': 'Name three primary colors.',
                'output.value': 'Red, yellow, blue.',
            })
            openinference.process(event, () => mapOtelAttributes(event))

            expect(event.properties!['$ai_input']).toEqual([{ role: 'user', content: 'Name three primary colors.' }])
            expect(event.properties!['$ai_output_choices']).toEqual([
                { role: 'assistant', content: 'Red, yellow, blue.' },
            ])
        })

        it('maps session.id and keeps user.id for the base mapping to strip', () => {
            const event = createEvent('$ai_span', {
                'openinference.span.kind': 'CHAIN',
                'session.id': 'session-42',
            })
            openinference.process(event, () => mapOtelAttributes(event))

            expect(event.properties!['$ai_session_id']).toBe('session-42')
            expect(event.properties!['session.id']).toBeUndefined()
        })
    })
})
