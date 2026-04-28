import { parseJSON } from '../../../../utils/json-parse'
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

/**
 * Minimal mock that replicates the subset of mapOtelAttributes behavior
 * needed by the vercel-ai middleware: parsing gen_ai.input/output.messages
 * into $ai_input/$ai_output_choices and promoting root spans to traces.
 */
function mockMapOtelAttributes(e: { event: string; properties?: Record<string, unknown> }): void {
    const props = e.properties ?? {}
    if (props['gen_ai.input.messages'] !== undefined) {
        const val = props['gen_ai.input.messages']
        props['$ai_input'] = typeof val === 'string' ? parseJSON(val) : val
        delete props['gen_ai.input.messages']
    }
    if (props['gen_ai.output.messages'] !== undefined) {
        const val = props['gen_ai.output.messages']
        props['$ai_output_choices'] = typeof val === 'string' ? parseJSON(val) : val
        delete props['gen_ai.output.messages']
    }
    if (e.event === '$ai_span' && !props['$ai_parent_id']) {
        e.event = '$ai_trace'
    }
}

describe('vercel-ai middleware', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        mockedMapOtelAttributes.mockImplementation(mockMapOtelAttributes)
    })

    describe('$ai_generation', () => {
        it('maps ai.prompt.messages to $ai_input and ai.response.text to $ai_output_choices', () => {
            const messages = JSON.stringify([
                { role: 'system', content: 'You are helpful.' },
                { role: 'user', content: [{ type: 'text', text: 'Hi' }] },
            ])
            const event = createEvent('$ai_generation', {
                'ai.operationId': 'ai.generateText.doGenerate',
                'ai.prompt.messages': messages,
                'ai.response.text': 'Hello there!',
                'gen_ai.system': 'openai.responses',
                'gen_ai.request.model': 'gpt-4o-mini',
                'gen_ai.usage.input_tokens': 23,
                'gen_ai.usage.output_tokens': 14,
            })
            convertOtelEvent(event)

            expect(event.properties!['$ai_input']).toEqual(parseJSON(messages))
            expect(event.properties!['$ai_output_choices']).toEqual([{ role: 'assistant', content: 'Hello there!' }])
            expect(event.properties!['ai.prompt.messages']).toBeUndefined()
            expect(event.properties!['ai.response.text']).toBeUndefined()
            expect(event.properties!['ai.operationId']).toBeUndefined()
        })

        it('strips Vercel-specific attributes', () => {
            const event = createEvent('$ai_generation', {
                'ai.operationId': 'ai.generateText.doGenerate',
                'ai.telemetry.functionId': 'my-func',
                'ai.model.id': 'gpt-4o-mini',
                'ai.model.provider': 'openai.responses',
                'ai.usage.promptTokens': 23,
                'ai.usage.completionTokens': 14,
                'ai.usage.tokens': 37,
                'ai.settings.maxRetries': 2,
                'ai.response.finishReason': 'stop',
                'ai.response.id': 'resp-123',
                'ai.response.model': 'gpt-4o-mini',
                'ai.response.timestamp': '2024-01-01T00:00:00Z',
                'ai.response.providerMetadata': '{}',
                'ai.request.headers.user-agent': 'ai/6.0.0',
                'ai.telemetry.metadata.posthog_distinct_id': 'user-1',
                'ai.telemetry.metadata.provider': 'vercel-ai',
                'operation.name': 'ai.generateText.doGenerate my-func',
                'resource.name': 'my-func',
            })
            convertOtelEvent(event)

            for (const key of Object.keys(event.properties!)) {
                expect(key).not.toMatch(/^ai\./)
                expect(key).not.toBe('operation.name')
                expect(key).not.toBe('resource.name')
            }
            expect(event.properties!['$ai_stop_reason']).toBe('stop')
        })

        it('maps gen_ai.response.finish_reasons array to $ai_stop_reason', () => {
            const event = createEvent('$ai_generation', {
                'ai.operationId': 'ai.generateText.doGenerate',
                'gen_ai.response.finish_reasons': ['length'],
            })
            convertOtelEvent(event)

            expect(event.properties!['gen_ai.response.finish_reasons']).toBeUndefined()
            expect(event.properties!['$ai_stop_reason']).toBe('length')
        })

        it('leaves $ai_stop_reason undefined when no finish reason is present', () => {
            const event = createEvent('$ai_generation', {
                'ai.operationId': 'ai.generateText.doGenerate',
            })
            convertOtelEvent(event)

            expect(event.properties!['$ai_stop_reason']).toBeUndefined()
        })
    })

    describe('$ai_trace (top-level span)', () => {
        it('extracts input/output state from ai.prompt JSON array on top-level span', () => {
            const messages = [
                { role: 'system', content: 'You are helpful.' },
                { role: 'user', content: [{ type: 'text', text: 'Hello' }] },
            ]
            const event = createEvent('$ai_span', {
                'ai.operationId': 'ai.generateText',
                'ai.prompt': JSON.stringify(messages),
                'ai.response.text': 'Hi there!',
            })
            convertOtelEvent(event)

            expect(event.event).toBe('$ai_trace')
            expect(event.properties!['$ai_input_state']).toEqual(messages[1])
            expect(event.properties!['$ai_output_state']).toEqual({ role: 'assistant', content: 'Hi there!' })
        })

        it('wraps plain string ai.prompt as user message', () => {
            const event = createEvent('$ai_span', {
                'ai.operationId': 'ai.generateText',
                'ai.prompt': 'Write a short story about a cat.',
                'ai.response.text': 'Once upon a time...',
            })
            convertOtelEvent(event)

            expect(event.event).toBe('$ai_trace')
            expect(event.properties!['$ai_input_state']).toEqual({
                role: 'user',
                content: 'Write a short story about a cat.',
            })
            expect(event.properties!['$ai_output_state']).toEqual({ role: 'assistant', content: 'Once upon a time...' })
        })

        it('prefers ai.prompt.messages over ai.prompt on provider-level spans', () => {
            const messages = [
                { role: 'system', content: 'You are helpful.' },
                { role: 'user', content: [{ type: 'text', text: 'Hello' }] },
            ]
            const event = createEvent('$ai_span', {
                'ai.operationId': 'ai.generateText',
                'ai.prompt.messages': JSON.stringify(messages),
                'ai.prompt': 'raw prompt',
                'ai.response.text': 'Hi there!',
            })
            convertOtelEvent(event)

            expect(event.properties!['$ai_input_state']).toEqual(messages[1])
        })
    })

    describe('tool call $ai_span', () => {
        it('maps tool call attributes to state properties', () => {
            const toolArgs = { latitude: 45.5, longitude: -73.5, location_name: 'Montreal' }
            const event = createEvent('$ai_span', {
                $ai_parent_id: 'parent-1',
                'ai.operationId': 'ai.toolCall',
                'ai.toolCall.name': 'get_weather',
                'ai.toolCall.id': 'call-123',
                'ai.toolCall.args': JSON.stringify(toolArgs),
                'ai.toolCall.result': '"Sunny, 25°C"',
            })
            convertOtelEvent(event)

            expect(event.properties!['$ai_span_name']).toBe('get_weather')
            expect(event.properties!['$ai_input_state']).toEqual(toolArgs)
            expect(event.properties!['$ai_output_state']).toBe('Sunny, 25°C')
            expect(event.properties!['ai.toolCall.name']).toBeUndefined()
            expect(event.properties!['ai.toolCall.id']).toBeUndefined()
            expect(event.properties!['ai.toolCall.args']).toBeUndefined()
            expect(event.properties!['ai.toolCall.result']).toBeUndefined()
        })

        it('keeps tool args as string when JSON parsing fails', () => {
            const event = createEvent('$ai_span', {
                $ai_parent_id: 'parent-1',
                'ai.operationId': 'ai.toolCall',
                'ai.toolCall.name': 'my_tool',
                'ai.toolCall.args': 'not json',
            })
            convertOtelEvent(event)
            expect(event.properties!['$ai_input_state']).toBe('not json')
        })
    })

    describe('sets $ai_lib', () => {
        it.each(['$ai_generation', '$ai_span'])('sets $ai_lib on %s events', (eventType) => {
            const event = createEvent(eventType, { 'ai.operationId': 'ai.generateText.doGenerate' })
            convertOtelEvent(event)
            expect(event.properties!['$ai_lib']).toBe('opentelemetry/vercel-ai')
        })
    })
})
