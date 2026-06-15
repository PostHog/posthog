import { mapOtelAttributes } from '../attribute-mapping'
import { convertOtelEvent } from '../index'
import { createEvent } from '../test-helpers'

jest.mock('../../metrics', () => ({
    aiOtelMiddlewareCounter: { labels: jest.fn().mockReturnValue({ inc: jest.fn() }) },
    aiOtelEventTypeCounter: { labels: jest.fn().mockReturnValue({ inc: jest.fn() }) },
}))

jest.mock('../attribute-mapping', () => ({
    mapOtelAttributes: jest.fn(),
}))

const mockedMapOtelAttributes = jest.mocked(mapOtelAttributes)

describe('pydantic-ai middleware', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    describe('$ai_trace (root span)', () => {
        beforeEach(() => {
            mockedMapOtelAttributes.mockImplementation((e) => {
                if (e.event === '$ai_span' && !e.properties?.['$ai_parent_id']) {
                    e.event = '$ai_trace'
                }
            })
        })

        it('extracts input from pydantic_ai.all_messages and output from final_result', () => {
            const messages = [
                { role: 'system', parts: [{ type: 'text', content: 'You are helpful' }] },
                { role: 'user', parts: [{ type: 'text', content: 'Hello' }] },
            ]
            const event = createEvent('$ai_span', {
                'pydantic_ai.all_messages': JSON.stringify(messages),
                final_result: 'The answer is 42',
                'gen_ai.agent.name': 'my-agent',
                'logfire.msg': 'agent run',
                'logfire.json_schema': '{}',
            })
            convertOtelEvent(event)

            expect(event.event).toBe('$ai_trace')
            expect(event.properties!['$ai_input_state']).toEqual(messages[1])
            expect(event.properties!['$ai_output_state']).toBe('The answer is 42')
            expect(event.properties!['$ai_span_name']).toBe('my-agent')
            expect(event.properties!['pydantic_ai.all_messages']).toBeUndefined()
            expect(event.properties!['final_result']).toBeUndefined()
            expect(event.properties!['gen_ai.agent.name']).toBeUndefined()
            expect(event.properties!['logfire.msg']).toBeUndefined()
            expect(event.properties!['logfire.json_schema']).toBeUndefined()
        })

        it('falls back to last non-user/system message for output when final_result is absent', () => {
            const messages = [
                { role: 'system', parts: [{ type: 'text', content: 'You are helpful' }] },
                { role: 'user', parts: [{ type: 'text', content: 'Hello' }] },
                { role: 'model-text-response', parts: [{ type: 'text', content: 'Hi there!' }] },
            ]
            const event = createEvent('$ai_span', {
                'pydantic_ai.all_messages': JSON.stringify(messages),
                'gen_ai.agent.name': 'my-agent',
            })
            convertOtelEvent(event)

            expect(event.event).toBe('$ai_trace')
            expect(event.properties!['$ai_input_state']).toEqual(messages[1])
            expect(event.properties!['$ai_output_state']).toEqual(messages[2])
        })

        it('parses final_result JSON string into object for $ai_output_state', () => {
            const structured = { name: 'Montreal', country: 'Canada', population: 1700000 }
            const event = createEvent('$ai_span', {
                'pydantic_ai.all_messages': JSON.stringify([
                    { role: 'user', parts: [{ type: 'text', content: 'Hello' }] },
                ]),
                final_result: JSON.stringify(structured),
            })
            convertOtelEvent(event)

            expect(event.properties!['$ai_output_state']).toEqual(structured)
        })

        it.each([
            ['number', '42'],
            ['boolean', 'true'],
            ['null', 'null'],
        ])('keeps final_result as string when parsed value is a %s', (_label, value) => {
            const event = createEvent('$ai_span', {
                'pydantic_ai.all_messages': JSON.stringify([
                    { role: 'user', parts: [{ type: 'text', content: 'Hello' }] },
                ]),
                final_result: value,
            })
            convertOtelEvent(event)

            expect(event.properties!['$ai_output_state']).toBe(value)
        })

        it('keeps final_result as plain string when not valid JSON', () => {
            const event = createEvent('$ai_span', {
                'pydantic_ai.all_messages': JSON.stringify([
                    { role: 'user', parts: [{ type: 'text', content: 'Hello' }] },
                ]),
                final_result: 'The answer is 42',
            })
            convertOtelEvent(event)

            expect(event.properties!['$ai_output_state']).toBe('The answer is 42')
        })

        it('prefers final_result over message fallback for output', () => {
            const messages = [
                { role: 'user', parts: [{ type: 'text', content: 'Hello' }] },
                { role: 'model-text-response', parts: [{ type: 'text', content: 'Hi there!' }] },
            ]
            const event = createEvent('$ai_span', {
                'pydantic_ai.all_messages': JSON.stringify(messages),
                final_result: 'The answer is 42',
            })
            convertOtelEvent(event)

            expect(event.properties!['$ai_output_state']).toBe('The answer is 42')
        })

        it('filters non-object items from pydantic_ai.all_messages', () => {
            const messages = [
                'not an object',
                { role: 'user', parts: [{ type: 'text', content: 'Hello' }] },
                42,
                null,
                [1, 2, 3],
                { role: 'model-text-response', parts: [{ type: 'text', content: 'Hi!' }] },
            ]
            const event = createEvent('$ai_span', {
                'pydantic_ai.all_messages': JSON.stringify(messages),
            })
            convertOtelEvent(event)

            expect(event.properties!['$ai_input_state']).toEqual(messages[1])
            expect(event.properties!['$ai_output_state']).toEqual(messages[5])
        })

        it('uses agent_name as fallback for $ai_span_name', () => {
            const event = createEvent('$ai_span', {
                'pydantic_ai.all_messages': '[]',
                agent_name: 'fallback-agent',
            })
            convertOtelEvent(event)
            expect(event.properties!['$ai_span_name']).toBe('fallback-agent')
            expect(event.properties!['agent_name']).toBeUndefined()
        })

        it('uses logfire.msg as $ai_span_name when no agent name and no $otel_span_name', () => {
            const event = createEvent('$ai_span', {
                'logfire.msg': 'agent run',
                'pydantic_ai.all_messages': '[]',
            })
            convertOtelEvent(event)
            expect(event.properties!['$ai_span_name']).toBe('agent run')
        })

        it('does not set $ai_span_name when no sources available', () => {
            const event = createEvent('$ai_span', {
                'pydantic_ai.all_messages': '[]',
            })
            convertOtelEvent(event)
            expect(event.properties!['$ai_span_name']).toBeUndefined()
        })

        it('maps model_name to $ai_model and strips it', () => {
            const event = createEvent('$ai_span', {
                'pydantic_ai.all_messages': '[]',
                model_name: 'openai:gpt-4o',
            })
            convertOtelEvent(event)
            expect(event.properties!['$ai_model']).toBe('openai:gpt-4o')
            expect(event.properties!['model_name']).toBeUndefined()
        })

        it('does not overwrite $ai_model when already set', () => {
            const event = createEvent('$ai_span', {
                'pydantic_ai.all_messages': '[]',
                $ai_model: 'existing-model',
                model_name: 'openai:gpt-4o',
            })
            convertOtelEvent(event)
            expect(event.properties!['$ai_model']).toBe('existing-model')
            expect(event.properties!['model_name']).toBeUndefined()
        })
    })

    describe('nested agent-run $ai_span', () => {
        it('extracts input/output and agent name from nested agent-run span', () => {
            const messages = [
                { role: 'user', parts: [{ type: 'text', content: 'Tell me about Python' }] },
                { role: 'model-text-response', parts: [{ type: 'text', content: 'Python was created in 1991.' }] },
            ]
            const event = createEvent('$ai_span', {
                $ai_parent_id: 'parent-trace-1',
                'pydantic_ai.all_messages': JSON.stringify(messages),
                final_result: 'Python was created in 1991.',
                'gen_ai.agent.name': 'research_agent',
                agent_name: 'research_agent',
                model_name: 'gpt-4o-mini',
                'logfire.msg': 'agent run',
                'logfire.json_schema': '{}',
            })
            convertOtelEvent(event)

            expect(event.event).toBe('$ai_span')
            expect(event.properties!['$ai_input_state']).toEqual(messages[0])
            expect(event.properties!['$ai_output_state']).toBe('Python was created in 1991.')
            expect(event.properties!['$ai_span_name']).toBe('research_agent')
            expect(event.properties!['$ai_model']).toBe('gpt-4o-mini')
            expect(event.properties!['pydantic_ai.all_messages']).toBeUndefined()
            expect(event.properties!['final_result']).toBeUndefined()
            expect(event.properties!['agent_name']).toBeUndefined()
            expect(event.properties!['gen_ai.agent.name']).toBeUndefined()
            expect(event.properties!['logfire.msg']).toBeUndefined()
            expect(event.properties!['logfire.json_schema']).toBeUndefined()
            expect(event.properties!['model_name']).toBeUndefined()
        })

        it('falls back to last assistant message when nested span has no final_result', () => {
            const messages = [
                { role: 'user', parts: [{ type: 'text', content: 'Hello' }] },
                { role: 'model-text-response', parts: [{ type: 'text', content: 'Hi there!' }] },
            ]
            const event = createEvent('$ai_span', {
                $ai_parent_id: 'parent-trace-1',
                'pydantic_ai.all_messages': JSON.stringify(messages),
                'gen_ai.agent.name': 'sub_agent',
            })
            convertOtelEvent(event)

            expect(event.event).toBe('$ai_span')
            expect(event.properties!['$ai_output_state']).toEqual(messages[1])
        })
    })

    describe('$ai_span with tool data', () => {
        it('maps tool_arguments and tool_response to state properties', () => {
            const toolArgs = { latitude: 45.5, longitude: -73.5 }
            const event = createEvent('$ai_span', {
                $ai_parent_id: 'parent-1',
                'logfire.msg': 'running tool: get_weather',
                tool_arguments: JSON.stringify(toolArgs),
                tool_response: 'Sunny, 25°C',
                'gen_ai.tool.name': 'get_weather',
                'gen_ai.tool.call.id': 'call-123',
                'logfire.json_schema': '{}',
            })
            convertOtelEvent(event)

            expect(event.properties!['$ai_input_state']).toEqual(toolArgs)
            expect(event.properties!['$ai_output_state']).toBe('Sunny, 25°C')
            expect(event.properties!['$ai_span_name']).toBe('get_weather')
            expect(event.properties!['tool_arguments']).toBeUndefined()
            expect(event.properties!['tool_response']).toBeUndefined()
            expect(event.properties!['gen_ai.tool.name']).toBeUndefined()
            expect(event.properties!['gen_ai.tool.call.id']).toBeUndefined()
            expect(event.properties!['logfire.msg']).toBeUndefined()
            expect(event.properties!['logfire.json_schema']).toBeUndefined()
        })

        it('parses tool_response JSON string into object for $ai_output_state', () => {
            const toolResponse = { temperature: 25, unit: 'celsius', condition: 'sunny' }
            const event = createEvent('$ai_span', {
                $ai_parent_id: 'parent-1',
                'logfire.msg': 'running tool: get_weather',
                tool_response: JSON.stringify(toolResponse),
                'gen_ai.tool.name': 'get_weather',
            })
            convertOtelEvent(event)

            expect(event.properties!['$ai_output_state']).toEqual(toolResponse)
        })

        it('keeps tool_response as plain string when not valid JSON', () => {
            const event = createEvent('$ai_span', {
                $ai_parent_id: 'parent-1',
                'logfire.msg': 'running tool: get_weather',
                tool_response: 'Sunny, 25°C',
            })
            convertOtelEvent(event)

            expect(event.properties!['$ai_output_state']).toBe('Sunny, 25°C')
        })

        it('keeps tool_arguments as string when JSON parsing fails', () => {
            const event = createEvent('$ai_span', {
                $ai_parent_id: 'parent-1',
                'logfire.msg': 'tool run',
                tool_arguments: 'not json',
            })
            convertOtelEvent(event)
            expect(event.properties!['$ai_input_state']).toBe('not json')
        })

        it('passes through already-parsed tool_arguments', () => {
            const toolArgs = { key: 'value' }
            const event = createEvent('$ai_span', {
                $ai_parent_id: 'parent-1',
                'logfire.msg': 'tool run',
                tool_arguments: toolArgs,
            })
            convertOtelEvent(event)
            expect(event.properties!['$ai_input_state']).toEqual(toolArgs)
        })
    })

    describe('plain $ai_span', () => {
        it('strips logfire keys and uses logfire.msg as $ai_span_name fallback', () => {
            const event = createEvent('$ai_span', {
                $ai_parent_id: 'parent-1',
                'logfire.msg': 'running 1 tool',
                'logfire.json_schema': '{}',
            })
            convertOtelEvent(event)

            expect(event.properties!['$ai_span_name']).toBe('running 1 tool')
            expect(event.properties!['logfire.msg']).toBeUndefined()
            expect(event.properties!['logfire.json_schema']).toBeUndefined()
        })
    })

    describe('$ai_generation', () => {
        it('strips logfire and model_request_parameters from generation events with openai provider', () => {
            const event = createEvent('$ai_generation', {
                'gen_ai.system': 'openai',
                'logfire.json_schema': '{"type": "object"}',
                'operation.cost': '0.001',
                model_request_parameters: '{"temperature": 0.7}',
            })
            convertOtelEvent(event)

            expect(mockedMapOtelAttributes).toHaveBeenCalledWith(event)
            expect(event.properties!['logfire.json_schema']).toBeUndefined()
            expect(event.properties!['operation.cost']).toBeUndefined()
            expect(event.properties!['model_request_parameters']).toBeUndefined()
        })
    })

    describe('strips redundant usage detail attributes', () => {
        it.each(['$ai_generation', '$ai_trace'])('strips gen_ai.usage.details.* from %s events', (eventType) => {
            const event = createEvent(eventType, {
                'logfire.msg': 'test',
                'gen_ai.usage.details.input_tokens': 100,
                'gen_ai.usage.details.output_tokens': 50,
            })
            convertOtelEvent(event)
            expect(event.properties!['gen_ai.usage.details.input_tokens']).toBeUndefined()
            expect(event.properties!['gen_ai.usage.details.output_tokens']).toBeUndefined()
        })
    })

    describe('sets $ai_lib', () => {
        it.each(['$ai_generation', '$ai_span', '$ai_trace'])(
            'sets $ai_lib to opentelemetry/pydantic-ai on %s events',
            (eventType) => {
                const event = createEvent(eventType, { 'logfire.msg': 'test' })
                convertOtelEvent(event)
                expect(event.properties!['$ai_lib']).toBe('opentelemetry/pydantic-ai')
            }
        )

        it('overwrites $ai_lib from generic OTel mapping', () => {
            const event = createEvent('$ai_generation', {
                'logfire.msg': 'test',
                $ai_lib: 'opentelemetry',
            })
            convertOtelEvent(event)
            expect(event.properties!['$ai_lib']).toBe('opentelemetry/pydantic-ai')
        })
    })
})
