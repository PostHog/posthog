import { PluginEvent } from '@posthog/plugin-scaffold'

import { extractToolCallNames } from './extract-tool-calls'
import { processAiToolCallExtraction } from './index'

describe('extractToolCallNames', () => {
    describe('OpenAI format', () => {
        it.each([
            [
                'single tool call',
                [
                    {
                        message: {
                            tool_calls: [{ type: 'function', function: { name: 'get_weather' } }],
                        },
                    },
                ],
                ['get_weather'],
            ],
            [
                'multiple tool calls in one choice',
                [
                    {
                        message: {
                            tool_calls: [
                                { type: 'function', function: { name: 'get_weather' } },
                                { type: 'function', function: { name: 'search_docs' } },
                            ],
                        },
                    },
                ],
                ['get_weather', 'search_docs'],
            ],
            [
                'tool calls across multiple choices',
                [
                    {
                        message: {
                            tool_calls: [{ type: 'function', function: { name: 'get_weather' } }],
                        },
                    },
                    {
                        message: {
                            tool_calls: [{ type: 'function', function: { name: 'search_docs' } }],
                        },
                    },
                ],
                ['get_weather', 'search_docs'],
            ],
            [
                'preserves duplicate tool names',
                [
                    {
                        message: {
                            tool_calls: [
                                { type: 'function', function: { name: 'get_weather' } },
                                { type: 'function', function: { name: 'get_weather' } },
                            ],
                        },
                    },
                ],
                ['get_weather', 'get_weather'],
            ],
        ])('%s', (_description, input, expected) => {
            expect(extractToolCallNames(input)).toEqual(expected)
        })
    })

    describe('Anthropic format', () => {
        it.each([
            [
                'single tool_use block',
                [
                    {
                        message: {
                            content: [{ type: 'tool_use', name: 'get_weather' }],
                        },
                    },
                ],
                ['get_weather'],
            ],
            [
                'mixed content (text + tool_use)',
                [
                    {
                        message: {
                            content: [
                                { type: 'text', text: 'Let me check the weather.' },
                                { type: 'tool_use', name: 'get_weather' },
                            ],
                        },
                    },
                ],
                ['get_weather'],
            ],
            [
                'multiple tool_use blocks',
                [
                    {
                        message: {
                            content: [
                                { type: 'tool_use', name: 'get_weather' },
                                { type: 'text', text: 'Now searching...' },
                                { type: 'tool_use', name: 'search_docs' },
                            ],
                        },
                    },
                ],
                ['get_weather', 'search_docs'],
            ],
        ])('%s', (_description, input, expected) => {
            expect(extractToolCallNames(input)).toEqual(expected)
        })
    })

    describe('malformed/missing data', () => {
        it.each([
            ['null', null, []],
            ['undefined', undefined, []],
            ['empty array', [], []],
            ['non-array', 'not an array', []],
            ['number', 42, []],
            ['choice without message', [{}], []],
            ['choice with null message', [{ message: null }], []],
            ['choice with empty message', [{ message: {} }], []],
            [
                'tool_calls with missing function name',
                [{ message: { tool_calls: [{ type: 'function', function: {} }] } }],
                [],
            ],
            ['tool_calls with null entries', [{ message: { tool_calls: [null, undefined] } }], []],
            ['content with non-tool_use type', [{ message: { content: [{ type: 'text', name: 'not_a_tool' }] } }], []],
        ])('%s', (_description, input, expected) => {
            expect(extractToolCallNames(input)).toEqual(expected)
        })
    })

    describe('no tool calls', () => {
        it('returns empty for text-only response', () => {
            const choices = [
                {
                    message: {
                        content: 'Hello, how can I help you?',
                        role: 'assistant',
                    },
                },
            ]
            expect(extractToolCallNames(choices)).toEqual([])
        })
    })
})

describe('processAiToolCallExtraction', () => {
    const createEvent = (event: string, properties: Record<string, unknown>): PluginEvent => ({
        distinct_id: 'user_123',
        ip: null,
        site_url: '',
        team_id: 1,
        now: new Date().toISOString(),
        event,
        uuid: '123e4567-e89b-12d3-a456-426614174000',
        properties,
    })

    it('extracts OpenAI tool calls from $ai_generation events', () => {
        const event = createEvent('$ai_generation', {
            $ai_output_choices: [
                {
                    message: {
                        tool_calls: [
                            { type: 'function', function: { name: 'get_weather' } },
                            { type: 'function', function: { name: 'search_docs' } },
                        ],
                    },
                },
            ],
        })

        const result = processAiToolCallExtraction(event)

        expect(result.properties!['$ai_tools_called']).toBe('["get_weather","search_docs"]')
        expect(result.properties!['$ai_tool_call_count']).toBe(2)
    })

    it('extracts Anthropic tool calls', () => {
        const event = createEvent('$ai_generation', {
            $ai_output_choices: [
                {
                    message: {
                        content: [
                            { type: 'text', text: 'Let me look that up.' },
                            { type: 'tool_use', name: 'web_search' },
                        ],
                    },
                },
            ],
        })

        const result = processAiToolCallExtraction(event)

        expect(result.properties!['$ai_tools_called']).toBe('["web_search"]')
        expect(result.properties!['$ai_tool_call_count']).toBe(1)
    })

    it('parses string $ai_output_choices', () => {
        const event = createEvent('$ai_generation', {
            $ai_output_choices: JSON.stringify([
                {
                    message: {
                        tool_calls: [{ type: 'function', function: { name: 'get_weather' } }],
                    },
                },
            ]),
        })

        const result = processAiToolCallExtraction(event)

        expect(result.properties!['$ai_tools_called']).toBe('["get_weather"]')
        expect(result.properties!['$ai_tool_call_count']).toBe(1)
    })

    it('does not set properties when no tool calls found', () => {
        const event = createEvent('$ai_generation', {
            $ai_output_choices: [
                {
                    message: {
                        content: 'Just a text response',
                    },
                },
            ],
        })

        const result = processAiToolCallExtraction(event)

        expect(result.properties!['$ai_tools_called']).toBeUndefined()
        expect(result.properties!['$ai_tool_call_count']).toBeUndefined()
    })

    it('skips non-generation events', () => {
        const event = createEvent('$ai_span', {
            $ai_output_choices: [
                {
                    message: {
                        tool_calls: [{ type: 'function', function: { name: 'get_weather' } }],
                    },
                },
            ],
        })

        const result = processAiToolCallExtraction(event)

        expect(result.properties!['$ai_tools_called']).toBeUndefined()
        expect(result.properties!['$ai_tool_call_count']).toBeUndefined()
    })

    it('respects user-provided $ai_tools_called', () => {
        const event = createEvent('$ai_generation', {
            $ai_tools_called: '["custom_tool"]',
            $ai_output_choices: [
                {
                    message: {
                        tool_calls: [{ type: 'function', function: { name: 'get_weather' } }],
                    },
                },
            ],
        })

        const result = processAiToolCallExtraction(event)

        expect(result.properties!['$ai_tools_called']).toBe('["custom_tool"]')
    })

    it('handles missing $ai_output_choices', () => {
        const event = createEvent('$ai_generation', {
            $ai_model: 'gpt-4',
        })

        const result = processAiToolCallExtraction(event)

        expect(result.properties!['$ai_tools_called']).toBeUndefined()
        expect(result.properties!['$ai_tool_call_count']).toBeUndefined()
    })

    it('handles events without properties', () => {
        const event: PluginEvent = {
            distinct_id: 'user_123',
            ip: null,
            site_url: '',
            team_id: 1,
            now: new Date().toISOString(),
            event: '$ai_generation',
            uuid: '123e4567-e89b-12d3-a456-426614174000',
        }

        const result = processAiToolCallExtraction(event)

        expect(result).toBe(event)
    })

    it('handles invalid JSON string in $ai_output_choices', () => {
        const event = createEvent('$ai_generation', {
            $ai_output_choices: 'not valid json',
        })

        const result = processAiToolCallExtraction(event)

        expect(result.properties!['$ai_tools_called']).toBeUndefined()
        expect(result.properties!['$ai_tool_call_count']).toBeUndefined()
    })
})
