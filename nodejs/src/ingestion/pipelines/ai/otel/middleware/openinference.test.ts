import { mapOtelAttributes } from '~/ingestion/pipelines/ai/otel/attribute-mapping'
import { createEvent } from '~/ingestion/pipelines/ai/otel/test-helpers'

import { openinference } from './openinference'

jest.mock('~/ingestion/pipelines/ai/otel/attribute-mapping', () => ({
    mapOtelAttributes: jest.fn(),
}))

const mockedMapOtelAttributes = jest.mocked(mapOtelAttributes)

describe('openinference middleware', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    describe('matches', () => {
        it.each([
            ['openinference.span.kind', { 'openinference.span.kind': 'LLM' }],
            ['any openinference.* key', { 'openinference.metadata': 'some-metadata' }],
        ])('detects openinference from %s', (_label, properties) => {
            const event = createEvent('$ai_generation', properties)
            expect(openinference.matches(event)).toBe(true)
        })

        it.each([
            ['no markers', {}],
            ['only llm.model_name', { 'llm.model_name': 'gpt-4o' }],
            ['only gen_ai.system', { 'gen_ai.system': 'openai' }],
        ])('does not match when %s', (_label, properties) => {
            const event = createEvent('$ai_generation', properties)
            expect(openinference.matches(event)).toBe(false)
        })
    })

    describe('process', () => {
        it('calls next() to run the shared attribute mapping', () => {
            const event = createEvent('$ai_generation', { 'openinference.span.kind': 'LLM' })
            openinference.process(event, () => mapOtelAttributes(event))
            expect(mockedMapOtelAttributes).toHaveBeenCalledWith(event)
        })

        it('reassembles flattened input messages into $ai_input', () => {
            const event = createEvent('$ai_generation', {
                'openinference.span.kind': 'LLM',
                'llm.input_messages.0.message.role': 'system',
                'llm.input_messages.0.message.content': 'You are helpful',
                'llm.input_messages.1.message.role': 'user',
                'llm.input_messages.1.message.content': 'Hello',
            })
            openinference.process(event, () => {})
            expect(event.properties!.$ai_input).toEqual([
                { role: 'system', content: 'You are helpful' },
                { role: 'user', content: 'Hello' },
            ])
            expect(event.properties!['llm.input_messages.0.message.role']).toBeUndefined()
        })

        it('reassembles flattened output messages into $ai_output_choices', () => {
            const event = createEvent('$ai_generation', {
                'openinference.span.kind': 'LLM',
                'llm.output_messages.0.message.role': 'assistant',
                'llm.output_messages.0.message.content': 'Hello there',
            })
            openinference.process(event, () => {})
            expect(event.properties!.$ai_output_choices).toEqual([{ role: 'assistant', content: 'Hello there' }])
        })

        it('rebuilds tool calls in the OpenAI shape (spec/tool_calling.md fixture)', () => {
            const event = createEvent('$ai_generation', {
                'openinference.span.kind': 'LLM',
                'llm.output_messages.0.message.role': 'assistant',
                'llm.output_messages.0.message.tool_calls.0.tool_call.id': 'call_001',
                'llm.output_messages.0.message.tool_calls.0.tool_call.function.name': 'get_weather',
                'llm.output_messages.0.message.tool_calls.0.tool_call.function.arguments': '{"location": "New York"}',
                'llm.output_messages.0.message.tool_calls.1.tool_call.id': 'call_002',
                'llm.output_messages.0.message.tool_calls.1.tool_call.function.name': 'get_weather',
                'llm.output_messages.0.message.tool_calls.1.tool_call.function.arguments': '{"location": "London"}',
            })
            openinference.process(event, () => {})
            expect(event.properties!.$ai_output_choices).toEqual([
                {
                    role: 'assistant',
                    tool_calls: [
                        {
                            type: 'function',
                            id: 'call_001',
                            function: { name: 'get_weather', arguments: '{"location": "New York"}' },
                        },
                        {
                            type: 'function',
                            id: 'call_002',
                            function: { name: 'get_weather', arguments: '{"location": "London"}' },
                        },
                    ],
                },
            ])
        })

        it('keeps tool result messages linked via tool_call_id and name', () => {
            const event = createEvent('$ai_generation', {
                'openinference.span.kind': 'LLM',
                'llm.input_messages.0.message.role': 'tool',
                'llm.input_messages.0.message.content': '{"temperature": 72, "condition": "sunny"}',
                'llm.input_messages.0.message.tool_call_id': 'call_abc123',
                'llm.input_messages.0.message.name': 'get_weather',
            })
            openinference.process(event, () => {})
            expect(event.properties!.$ai_input).toEqual([
                {
                    role: 'tool',
                    content: '{"temperature": 72, "condition": "sunny"}',
                    tool_call_id: 'call_abc123',
                    name: 'get_weather',
                },
            ])
        })

        it('does not overwrite $ai_input already set by the shared mapping', () => {
            const event = createEvent('$ai_generation', {
                'openinference.span.kind': 'LLM',
                'llm.input_messages.0.message.role': 'user',
                'llm.input_messages.0.message.content': 'open-inference',
            })
            openinference.process(event, () => {
                event.properties!.$ai_input = [{ role: 'user', content: 'gen-ai' }]
            })
            expect(event.properties!.$ai_input).toEqual([{ role: 'user', content: 'gen-ai' }])
            expect(event.properties!['llm.input_messages.0.message.role']).toBeUndefined()
        })

        it('parses llm.tools json_schema entries into $ai_tools', () => {
            const event = createEvent('$ai_generation', {
                'openinference.span.kind': 'LLM',
                'llm.tools.0.tool.json_schema': '{"type": "function", "function": {"name": "get_weather"}}',
            })
            openinference.process(event, () => {})
            expect(event.properties!.$ai_tools).toEqual([{ type: 'function', function: { name: 'get_weather' } }])
            expect(event.properties!['llm.tools.0.tool.json_schema']).toBeUndefined()
        })

        it('maps input.value/output.value to state on $ai_span events', () => {
            const event = createEvent('$ai_span', {
                'openinference.span.kind': 'CHAIN',
                'input.value': '{"question": "hello"}',
                'input.mime_type': 'application/json',
                'output.value': 'plain text answer',
                'output.mime_type': 'text/plain',
            })
            openinference.process(event, () => {})
            expect(event.properties!.$ai_input_state).toEqual({ question: 'hello' })
            expect(event.properties!.$ai_output_state).toBe('plain text answer')
            expect(event.properties!['input.value']).toBeUndefined()
            expect(event.properties!['input.mime_type']).toBeUndefined()
        })

        it('drops input.value/output.value on generation events without mapping to state', () => {
            const event = createEvent('$ai_generation', {
                'openinference.span.kind': 'LLM',
                'input.value': '{"messages": []}',
            })
            openinference.process(event, () => {})
            expect(event.properties!.$ai_input_state).toBeUndefined()
            expect(event.properties!['input.value']).toBeUndefined()
        })

        it('sets $ai_lib and strips classification and leftover flattened keys', () => {
            const event = createEvent('$ai_generation', {
                'openinference.span.kind': 'LLM',
                'openinference.metadata': 'some-metadata',
                'llm.invocation_parameters': '{"temperature": 0}',
                'llm.token_count.total': 200,
                'llm.input_messages.0.message.contents.0.message_content.type': 'text',
                'llm.input_messages.0.message.contents.0.message_content.text': 'multimodal part',
                'embedding.embeddings.0.embedding.vector': [0.1, 0.2],
                custom_property: 'kept',
            })
            openinference.process(event, () => {})
            expect(event.properties!.$ai_lib).toBe('opentelemetry/openinference')
            expect(event.properties!['openinference.span.kind']).toBeUndefined()
            expect(event.properties!['openinference.metadata']).toBeUndefined()
            expect(event.properties!['llm.invocation_parameters']).toBeUndefined()
            expect(event.properties!['llm.token_count.total']).toBeUndefined()
            expect(event.properties!['llm.input_messages.0.message.contents.0.message_content.text']).toBeUndefined()
            expect(event.properties!['embedding.embeddings.0.embedding.vector']).toBeUndefined()
            expect(event.properties!.custom_property).toBe('kept')
        })
    })
})
