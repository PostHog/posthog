import { PluginEvent } from '@posthog/plugin-scaffold'

import { mapOtelAttributes } from './attribute-mapping'
import { convertOtelEvent } from './index'

jest.mock('./attribute-mapping', () => ({
    mapOtelAttributes: jest.fn(),
}))

const mockedMapOtelAttributes = jest.mocked(mapOtelAttributes)

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

describe('convertOtelEvent', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    describe('provider detection', () => {
        it.each([
            ['no provider properties', {}],
            ['unknown provider', { 'gen_ai.system': 'unknown-provider' }],
            ['non-string gen_ai.system', { 'gen_ai.system': 123 }],
        ])('runs general mapping directly when %s', (_label, properties) => {
            const event = createEvent('$ai_generation', properties)
            convertOtelEvent(event)
            expect(mockedMapOtelAttributes).toHaveBeenCalledWith(event)
        })

        it('detects provider from gen_ai.system', () => {
            const event = createEvent('$ai_generation', { 'gen_ai.system': 'openai' })
            convertOtelEvent(event)
            expect(mockedMapOtelAttributes).toHaveBeenCalledWith(event)
        })

        it('falls back to gen_ai.provider.name', () => {
            const event = createEvent('$ai_generation', { 'gen_ai.provider.name': 'anthropic' })
            convertOtelEvent(event)
            expect(mockedMapOtelAttributes).toHaveBeenCalledWith(event)
        })

        it('prefers gen_ai.system over gen_ai.provider.name', () => {
            const event = createEvent('$ai_generation', {
                'gen_ai.system': 'openai',
                'gen_ai.provider.name': 'anthropic',
            })
            convertOtelEvent(event)
            expect(mockedMapOtelAttributes).toHaveBeenCalledWith(event)
        })

        it('detects pydantic-ai from pydantic_ai.all_messages attribute', () => {
            const event = createEvent('$ai_span', {
                'pydantic_ai.all_messages': '[]',
            })
            convertOtelEvent(event)
            expect(mockedMapOtelAttributes).toHaveBeenCalledWith(event)
        })

        it('detects pydantic-ai from logfire.msg attribute', () => {
            const event = createEvent('$ai_span', {
                'logfire.msg': 'running 1 tool',
            })
            convertOtelEvent(event)
            expect(mockedMapOtelAttributes).toHaveBeenCalledWith(event)
        })
    })

    describe('pydantic-ai middleware on $ai_trace (root span)', () => {
        beforeEach(() => {
            // mapOtelAttributes promotes $ai_span → $ai_trace for root spans
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
    })

    describe('pydantic-ai middleware on $ai_span with tool data', () => {
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

    describe('pydantic-ai middleware on plain $ai_span', () => {
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
})
