import { parseJSON } from '~/common/utils/json-parse'
import { mapOtelAttributes } from '~/ingestion/pipelines/ai/otel/attribute-mapping'
import { convertOtelEvent } from '~/ingestion/pipelines/ai/otel/index'
import { createEvent } from '~/ingestion/pipelines/ai/otel/test-helpers'

jest.mock('~/ingestion/pipelines/ai/metrics', () => ({
    aiOtelMiddlewareCounter: { labels: jest.fn().mockReturnValue({ inc: jest.fn() }) },
    aiOtelEventTypeCounter: { labels: jest.fn().mockReturnValue({ inc: jest.fn() }) },
}))

jest.mock('~/ingestion/pipelines/ai/otel/attribute-mapping', () => ({
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
    const mappings: Record<string, string> = {
        'gen_ai.usage.input_tokens': '$ai_input_tokens',
        'gen_ai.usage.output_tokens': '$ai_output_tokens',
        'gen_ai.usage.cache_read.input_tokens': '$ai_cache_read_input_tokens',
        'gen_ai.usage.cache_creation.input_tokens': '$ai_cache_creation_input_tokens',
        'gen_ai.response.model': '$ai_model',
        'gen_ai.provider.name': '$ai_provider',
    }
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
    for (const [otelKey, phKey] of Object.entries(mappings)) {
        if (props[otelKey] !== undefined) {
            props[phKey] = props[otelKey]
            delete props[otelKey]
        }
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
            expect(event.properties!['functionId']).toBe('my-func')
            expect(event.properties!['$ai_stop_reason']).toBe('stop')
        })

        it('ignores empty functionId telemetry', () => {
            const event = createEvent('$ai_generation', {
                'ai.operationId': 'ai.generateText.doGenerate',
                'ai.telemetry.functionId': '',
            })
            convertOtelEvent(event)

            expect(event.properties!['functionId']).toBeUndefined()
            expect(event.properties!['ai.telemetry.functionId']).toBeUndefined()
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

        it('normalizes AI SDK v7 detailed usage without relying on global cache semantics', () => {
            const event = createEvent('$ai_generation', {
                'ai.operationId': 'ai.streamText.doStream',
                'gen_ai.provider.name': 'gateway',
                'gen_ai.response.model': 'gemini-2.5-pro',
                'gen_ai.usage.input_tokens': 100,
                'gen_ai.usage.output_tokens': 20,
                'gen_ai.usage.cache_read.input_tokens': 80,
                'gen_ai.usage.cache_creation.input_tokens': 10,
                'ai.usage.inputTokenDetails.noCacheTokens': 10,
                'ai.usage.outputTokenDetails.textTokens': 15,
                'ai.usage.outputTokenDetails.reasoningTokens': 5,
            })
            convertOtelEvent(event)

            expect(event.properties!['$ai_provider']).toBe('gateway')
            expect(event.properties!['$ai_model']).toBe('gemini-2.5-pro')
            expect(event.properties!['$ai_input_tokens']).toBe(100)
            expect(event.properties!['$ai_output_tokens']).toBe(20)
            expect(event.properties!['$ai_cache_read_input_tokens']).toBe(80)
            expect(event.properties!['$ai_cache_creation_input_tokens']).toBe(10)
            expect(event.properties!['$ai_reasoning_tokens']).toBe(5)
            expect(event.properties!['$ai_cache_reporting_exclusive']).toBe(false)
            expect(event.properties!['$ai_framework']).toBe('vercel')
            expect(event.properties!['$ai_text_output_tokens']).toBe(15)
            expect(event.properties!['ai.usage.inputTokenDetails.noCacheTokens']).toBeUndefined()
            expect(event.properties!['ai.usage.outputTokenDetails.textTokens']).toBeUndefined()
        })

        it('preserves explicit cache reporting semantics on AI SDK v7 spans', () => {
            const event = createEvent('$ai_generation', {
                'ai.operationId': 'ai.generateText.doGenerate',
                'gen_ai.usage.cache_read.input_tokens': 80,
                $ai_cache_reporting_exclusive: true,
            })
            convertOtelEvent(event)

            expect(event.properties!['$ai_cache_reporting_exclusive']).toBe(true)
            expect(event.properties!['$ai_framework']).toBe('vercel')
        })

        it('does not add AI SDK v7 cache semantics when detailed cache usage is absent', () => {
            const event = createEvent('$ai_generation', {
                'ai.operationId': 'ai.generateText.doGenerate',
                'gen_ai.usage.input_tokens': 100,
                'gen_ai.usage.output_tokens': 20,
            })
            convertOtelEvent(event)

            expect(event.properties!['$ai_input_tokens']).toBe(100)
            expect(event.properties!['$ai_output_tokens']).toBe(20)
            expect(event.properties!['$ai_cache_reporting_exclusive']).toBeUndefined()
            expect(event.properties!['$ai_framework']).toBe('vercel')
        })

        it('preserves explicit text output tokens when AI SDK v7 reasoning details are present', () => {
            const event = createEvent('$ai_generation', {
                'ai.operationId': 'ai.streamText.doStream',
                'gen_ai.response.model': 'gemini-2.5-pro',
                'gen_ai.usage.output_tokens': 20,
                'ai.usage.outputTokenDetails.reasoningTokens': 5,
                $ai_text_output_tokens: 99,
            })
            convertOtelEvent(event)

            expect(event.properties!['$ai_output_tokens']).toBe(20)
            expect(event.properties!['$ai_reasoning_tokens']).toBe(5)
            expect(event.properties!['$ai_text_output_tokens']).toBe(99)
        })

        it('does not split text output tokens for non-Gemini reasoning models', () => {
            const event = createEvent('$ai_generation', {
                'ai.operationId': 'ai.streamText.doStream',
                'gen_ai.response.model': 'o1-mini',
                'gen_ai.usage.output_tokens': 20,
                'ai.usage.outputTokenDetails.textTokens': 15,
                'ai.usage.outputTokenDetails.reasoningTokens': 5,
            })
            convertOtelEvent(event)

            expect(event.properties!['$ai_output_tokens']).toBe(20)
            expect(event.properties!['$ai_reasoning_tokens']).toBe(5)
            expect(event.properties!['$ai_text_output_tokens']).toBeUndefined()
            expect(event.properties!['ai.usage.outputTokenDetails.textTokens']).toBeUndefined()
        })

        it('derives Gemini text output tokens when AI SDK v7 omits text token details', () => {
            const event = createEvent('$ai_generation', {
                'ai.operationId': 'ai.streamText.doStream',
                'gen_ai.response.model': 'gemini-2.5-pro',
                'gen_ai.usage.output_tokens': 20,
                'ai.usage.outputTokenDetails.reasoningTokens': 5,
            })
            convertOtelEvent(event)

            expect(event.properties!['$ai_output_tokens']).toBe(20)
            expect(event.properties!['$ai_reasoning_tokens']).toBe(5)
            expect(event.properties!['$ai_text_output_tokens']).toBe(15)
        })

        it('leaves $ai_stop_reason undefined when no finish reason is present', () => {
            const event = createEvent('$ai_generation', {
                'ai.operationId': 'ai.generateText.doGenerate',
            })
            convertOtelEvent(event)

            expect(event.properties!['$ai_stop_reason']).toBeUndefined()
        })

        it.each([
            ['posthog_distinct_id', 'user-1'],
            ['$ai_session_id', 'session-123'],
            ['$ai_prompt_name', 'my-prompt'],
            ['$ai_prompt_version', 'v2'],
            ['$ai_prompt_version', 2],
        ])('promotes ai.telemetry.metadata.%s to event properties', (key, value) => {
            const event = createEvent('$ai_generation', {
                'ai.operationId': 'ai.generateText.doGenerate',
                [`ai.telemetry.metadata.${key}`]: value,
                'ai.telemetry.metadata.org_id': 'org-456',
            })
            convertOtelEvent(event)

            expect(event.properties![key]).toBe(value)
            expect(event.properties!['org_id']).toBeUndefined()
            expect(event.properties![`ai.telemetry.metadata.${key}`]).toBeUndefined()
        })

        it('uses posthog_distinct_id as the event distinct_id', () => {
            const event = createEvent('$ai_generation', {
                'ai.operationId': 'ai.generateText.doGenerate',
                'ai.telemetry.metadata.posthog_distinct_id': 'user-1',
            })
            convertOtelEvent(event)

            expect(event.distinct_id).toBe('user-1')
        })

        it('ignores empty posthog_distinct_id metadata', () => {
            const event = createEvent('$ai_generation', {
                'ai.operationId': 'ai.generateText.doGenerate',
                'ai.telemetry.metadata.posthog_distinct_id': '',
            })
            convertOtelEvent(event)

            expect(event.properties!['posthog_distinct_id']).toBeUndefined()
            expect(event.distinct_id).toBe('user-123')
        })

        it.each(['$ai_session_id', '$ai_prompt_name', '$ai_prompt_version'])(
            'ignores empty ai.telemetry.metadata.%s',
            (key) => {
                const event = createEvent('$ai_generation', {
                    'ai.operationId': 'ai.generateText.doGenerate',
                    [`ai.telemetry.metadata.${key}`]: '',
                })
                convertOtelEvent(event)

                expect(event.properties![key]).toBeUndefined()
                expect(event.properties![`ai.telemetry.metadata.${key}`]).toBeUndefined()
            }
        )

        it.each([0, -1, 1.5])('ignores invalid numeric ai.telemetry.metadata.$ai_prompt_version=%s', (value) => {
            const event = createEvent('$ai_generation', {
                'ai.operationId': 'ai.generateText.doGenerate',
                'ai.telemetry.metadata.$ai_prompt_version': value,
            })
            convertOtelEvent(event)

            expect(event.properties!['$ai_prompt_version']).toBeUndefined()
            expect(event.properties!['ai.telemetry.metadata.$ai_prompt_version']).toBeUndefined()
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

        // AI SDK v6 records ai.prompt on top-level streamText/generateText spans as
        // a { system, messages } object rather than a bare array. Without object
        // handling, $ai_input/$ai_input_state were silently dropped.
        it('extracts input from ai.prompt { system, messages } object (AI SDK v6 streamText)', () => {
            const messages = [{ role: 'user', content: 'Hello' }]
            const event = createEvent('$ai_span', {
                'ai.operationId': 'ai.streamText',
                'ai.prompt': JSON.stringify({ system: 'You are helpful.', messages }),
                'ai.response.text': 'Hi there!',
            })
            convertOtelEvent(event)

            expect(event.event).toBe('$ai_trace')
            expect(event.properties!['$ai_input']).toEqual([
                { role: 'system', content: 'You are helpful.' },
                ...messages,
            ])
            expect(event.properties!['$ai_input_state']).toEqual(messages[0])
            expect(event.properties!['$ai_output_state']).toEqual({ role: 'assistant', content: 'Hi there!' })
        })

        it('extracts input from ai.prompt { system, prompt } object (generateObject)', () => {
            const event = createEvent('$ai_span', {
                'ai.operationId': 'ai.generateObject',
                'ai.prompt': JSON.stringify({ system: 'You are helpful.', prompt: 'Write a haiku.' }),
                'ai.response.text': '...',
            })
            convertOtelEvent(event)

            expect(event.properties!['$ai_input']).toEqual([
                { role: 'system', content: 'You are helpful.' },
                { role: 'user', content: 'Write a haiku.' },
            ])
            expect(event.properties!['$ai_input_state']).toEqual({ role: 'user', content: 'Write a haiku.' })
        })

        it('uses the last user message for $ai_input_state on multi-turn traces', () => {
            const messages = [
                { role: 'user', content: 'First question' },
                { role: 'assistant', content: 'First answer' },
                { role: 'user', content: 'Second question' },
            ]
            const event = createEvent('$ai_span', {
                'ai.operationId': 'ai.streamText',
                'ai.prompt': JSON.stringify({ messages }),
                'ai.response.text': 'Second answer',
            })
            convertOtelEvent(event)

            expect(event.properties!['$ai_input_state']).toEqual({ role: 'user', content: 'Second question' })
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

    describe('functionId as $ai_span_name', () => {
        it('overrides the generic name on a top-level wrapper span promoted to $ai_trace', () => {
            const event = createEvent('$ai_span', {
                'ai.operationId': 'ai.generateText',
                'ai.telemetry.functionId': 'my-func',
                $ai_span_name: 'ai.generateText',
            })
            convertOtelEvent(event)

            expect(event.event).toBe('$ai_trace')
            expect(event.properties!['$ai_span_name']).toBe('my-func')
        })

        it('overrides the generic name on a $ai_trace event', () => {
            const event = createEvent('$ai_trace', {
                'ai.operationId': 'ai.generateText',
                'ai.telemetry.functionId': 'my-func',
                $ai_span_name: 'ai.generateText',
            })
            convertOtelEvent(event)

            expect(event.properties!['$ai_span_name']).toBe('my-func')
        })

        it('leaves $ai_span_name untouched when functionId is empty', () => {
            const event = createEvent('$ai_trace', {
                'ai.operationId': 'ai.generateText',
                'ai.telemetry.functionId': '',
                $ai_span_name: 'ai.generateText',
            })
            convertOtelEvent(event)

            expect(event.properties!['$ai_span_name']).toBe('ai.generateText')
        })

        it('leaves $ai_span_name untouched when no functionId is set', () => {
            const event = createEvent('$ai_trace', {
                'ai.operationId': 'ai.generateText',
                $ai_span_name: 'ai.generateText',
            })
            convertOtelEvent(event)

            expect(event.properties!['$ai_span_name']).toBe('ai.generateText')
        })

        it('does not override $ai_span_name on a .doGenerate generation span', () => {
            const event = createEvent('$ai_generation', {
                'ai.operationId': 'ai.generateText.doGenerate',
                'ai.telemetry.functionId': 'my-func',
                $ai_span_name: 'ai.generateText.doGenerate',
            })
            convertOtelEvent(event)

            expect(event.properties!['$ai_span_name']).toBe('ai.generateText.doGenerate')
        })

        it('preserves the tool name on an ai.toolCall span carrying functionId', () => {
            const event = createEvent('$ai_span', {
                $ai_parent_id: 'parent-1',
                'ai.operationId': 'ai.toolCall',
                'ai.telemetry.functionId': 'my-func',
                'ai.toolCall.name': 'get_weather',
            })
            convertOtelEvent(event)

            expect(event.properties!['$ai_span_name']).toBe('get_weather')
        })
    })

    describe('sets $ai_lib', () => {
        it.each(['$ai_generation', '$ai_span'])('sets $ai_lib on %s events', (eventType) => {
            const event = createEvent(eventType, { 'ai.operationId': 'ai.generateText.doGenerate' })
            convertOtelEvent(event)
            expect(event.properties!['$ai_lib']).toBe('opentelemetry/vercel-ai')
            expect(event.properties!['$ai_framework']).toBe('vercel')
        })
    })
})
