import { mapOtelAttributes } from '~/ingestion/pipelines/ai/otel/attribute-mapping'
import { createEvent } from '~/ingestion/pipelines/ai/otel/test-helpers'

import { langwatch } from './langwatch'

jest.mock('~/ingestion/pipelines/ai/otel/attribute-mapping', () => ({
    mapOtelAttributes: jest.fn(),
}))

describe('langwatch middleware', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    describe('matches', () => {
        it.each([
            ['langwatch.gen_ai.streaming', { 'langwatch.gen_ai.streaming': false }],
            ['langwatch.input', { 'langwatch.input': '{"type":"json","value":[]}' }],
        ])('detects langwatch from %s', (_label, properties) => {
            expect(langwatch.matches(createEvent('$ai_generation', properties))).toBe(true)
        })

        it('does not match plain gen_ai spans', () => {
            expect(langwatch.matches(createEvent('$ai_generation', { 'gen_ai.request.model': 'gpt-4.1' }))).toBe(false)
        })
    })

    describe('process', () => {
        it('unwraps captured chat messages and response choices into $ai_input / $ai_output_choices', () => {
            const event = createEvent('$ai_generation', {
                'langwatch.gen_ai.streaming': false,
                'langwatch.input': JSON.stringify({
                    type: 'json',
                    value: [
                        { role: 'system', content: 'Be terse.' },
                        { role: 'user', content: 'Capital of France?' },
                    ],
                }),
                'langwatch.output': JSON.stringify({
                    type: 'json',
                    value: {
                        id: 'chatcmpl-1',
                        choices: [
                            {
                                index: 0,
                                finish_reason: 'stop',
                                message: { role: 'assistant', content: 'Paris.', refusal: '' },
                            },
                        ],
                    },
                }),
            })
            langwatch.process(event, () => mapOtelAttributes(event))

            const props = event.properties!
            expect(props['$ai_input']).toEqual([
                { role: 'system', content: 'Be terse.' },
                { role: 'user', content: 'Capital of France?' },
            ])
            expect(props['$ai_output_choices']).toEqual([{ role: 'assistant', content: 'Paris.' }])
            expect(props['$ai_stop_reason']).toBe('stop')
            expect(props['$ai_lib']).toBe('opentelemetry/langwatch')
            expect(props['langwatch.input']).toBeUndefined()
            expect(props['langwatch.output']).toBeUndefined()
            expect(props['langwatch.gen_ai.streaming']).toBeUndefined()
        })

        it('preserves tool_calls on captured response messages', () => {
            const event = createEvent('$ai_generation', {
                'langwatch.output': JSON.stringify({
                    type: 'json',
                    value: {
                        choices: [
                            {
                                index: 0,
                                finish_reason: 'tool_calls',
                                message: {
                                    role: 'assistant',
                                    content: null,
                                    tool_calls: [
                                        {
                                            id: 'call_1',
                                            type: 'function',
                                            function: { name: 'get_weather', arguments: '{"location":"Paris"}' },
                                        },
                                    ],
                                },
                            },
                        ],
                    },
                }),
            })
            langwatch.process(event, () => mapOtelAttributes(event))

            expect(event.properties!['$ai_output_choices']).toEqual([
                {
                    role: 'assistant',
                    content: null,
                    tool_calls: [
                        {
                            id: 'call_1',
                            type: 'function',
                            function: { name: 'get_weather', arguments: '{"location":"Paris"}' },
                        },
                    ],
                },
            ])
            expect(event.properties!['$ai_stop_reason']).toBe('tool_calls')
        })

        it('converts accumulated streaming text output into an assistant message', () => {
            const event = createEvent('$ai_generation', {
                'langwatch.output': JSON.stringify({ type: 'text', value: 'Red, yellow, blue.' }),
            })
            langwatch.process(event, () => mapOtelAttributes(event))

            expect(event.properties!['$ai_output_choices']).toEqual([
                { role: 'assistant', content: 'Red, yellow, blue.' },
            ])
        })

        it('converts Responses API output items and prepends instructions as a system message', () => {
            const event = createEvent('$ai_generation', {
                'langwatch.instructions': 'Be terse.',
                'langwatch.input': JSON.stringify({ type: 'text', value: 'Capital of France?' }),
                'langwatch.output': JSON.stringify({
                    type: 'json',
                    value: {
                        output: [
                            {
                                type: 'message',
                                role: 'assistant',
                                content: [{ type: 'output_text', text: 'Paris.' }],
                            },
                        ],
                    },
                }),
            })
            langwatch.process(event, () => mapOtelAttributes(event))

            const props = event.properties!
            expect(props['$ai_input']).toEqual([
                { role: 'system', content: 'Be terse.' },
                { role: 'user', content: 'Capital of France?' },
            ])
            expect(props['$ai_output_choices']).toEqual([{ role: 'assistant', content: 'Paris.' }])
        })

        it.each([
            ['malformed json', 'not-json{{'],
            ['missing value key', '{"type":"json"}'],
        ])('leaves $ai_input unset when langwatch.input is %s', (_label, input) => {
            const event = createEvent('$ai_generation', { 'langwatch.input': input })
            langwatch.process(event, () => mapOtelAttributes(event))

            expect(event.properties!['$ai_input']).toBeUndefined()
            expect(event.properties!['langwatch.input']).toBeUndefined()
        })

        it('does not overwrite $ai_input or $ai_stop_reason set by the base mapping', () => {
            const event = createEvent('$ai_generation', {
                $ai_input: [{ role: 'user', content: 'canonical' }],
                $ai_stop_reason: 'length',
                'langwatch.input': JSON.stringify({ type: 'json', value: [{ role: 'user', content: 'stale' }] }),
                'langwatch.output': JSON.stringify({
                    type: 'json',
                    value: { choices: [{ index: 0, finish_reason: 'stop', message: { role: 'assistant' } }] },
                }),
            })
            langwatch.process(event, () => mapOtelAttributes(event))

            expect(event.properties!['$ai_input']).toEqual([{ role: 'user', content: 'canonical' }])
            expect(event.properties!['$ai_stop_reason']).toBe('length')
        })

        it('strips HTTP transport noise', () => {
            const event = createEvent('$ai_generation', {
                'langwatch.gen_ai.streaming': true,
                'http.request.method': 'POST',
                'http.response.status_code': 200,
                'url.path': '/v1/chat/completions',
                'gen_ai.usage.total_tokens': 28,
            })
            langwatch.process(event, () => mapOtelAttributes(event))

            const props = event.properties!
            expect(props['http.request.method']).toBeUndefined()
            expect(props['http.response.status_code']).toBeUndefined()
            expect(props['url.path']).toBeUndefined()
            expect(props['gen_ai.usage.total_tokens']).toBeUndefined()
        })
    })
})
