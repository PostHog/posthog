import { PluginEvent } from '@posthog/plugin-scaffold'

import { extractToolCallNames } from './extract-tool-calls'
import { processAiToolCallExtraction } from './index'

describe('extractToolCallNames', () => {
    describe('OpenAI format (message.tool_calls)', () => {
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

    describe('normalized format (content with type=function)', () => {
        it.each([
            [
                'single function content block',
                [
                    {
                        content: [{ type: 'function', function: { name: 'get_weather' }, id: 'call_abc' }],
                        role: 'assistant',
                    },
                ],
                ['get_weather'],
            ],
            [
                'multiple function content blocks',
                [
                    {
                        content: [
                            { type: 'function', function: { name: 'get_weather' }, id: 'call_1' },
                            { type: 'function', function: { name: 'search_docs' }, id: 'call_2' },
                        ],
                        role: 'assistant',
                    },
                ],
                ['get_weather', 'search_docs'],
            ],
        ])('%s', (_description, input, expected) => {
            expect(extractToolCallNames(input)).toEqual(expected)
        })
    })

    describe('Anthropic format (message.content with tool_use)', () => {
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

    describe('Python repr format (OpenAI Agents SDK)', () => {
        it.each([
            [
                'single ResponseFunctionToolCall',
                "ResponseFunctionToolCall(arguments='{\"city\":\"Montreal\"}', call_id='call_abc', name='get_weather', type='function_call')",
                ['get_weather'],
            ],
            [
                'multiple ResponseFunctionToolCalls in array',
                "[ResponseFunctionToolCall(name='get_weather', type='function_call'), ResponseFunctionToolCall(name='search_docs', type='function_call')]",
                ['get_weather', 'search_docs'],
            ],
            [
                'mixed with non-tool content',
                "[ResponseOutputMessage(content=[ResponseOutputText(text='hello')]), ResponseFunctionToolCall(name='transfer_to_agent', type='function_call')]",
                ['transfer_to_agent'],
            ],
        ])('%s', (_description, rawString, expected) => {
            // Python repr strings fail JSON parse, so pass as rawString fallback
            expect(extractToolCallNames(undefined, rawString)).toEqual(expected)
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

    it('extracts normalized format with content.type=function', () => {
        const event = createEvent('$ai_generation', {
            $ai_output_choices: [
                {
                    content: [{ type: 'function', function: { name: 'get_weather' }, id: 'call_abc' }],
                    role: 'assistant',
                },
            ],
        })

        const result = processAiToolCallExtraction(event)

        expect(result.properties!['$ai_tools_called']).toBe('["get_weather"]')
        expect(result.properties!['$ai_tool_call_count']).toBe(1)
    })

    it('extracts from Python repr string (OpenAI Agents SDK)', () => {
        const event = createEvent('$ai_generation', {
            $ai_output_choices:
                "[ResponseFunctionToolCall(arguments='{\"city\":\"Montreal\"}', call_id='call_V2E', name='get_weather', type='function_call')]",
        })

        const result = processAiToolCallExtraction(event)

        expect(result.properties!['$ai_tools_called']).toBe('["get_weather"]')
        expect(result.properties!['$ai_tool_call_count']).toBe(1)
    })

    it('parses string $ai_output_choices (valid JSON)', () => {
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

    it('does not set properties for non-tool Python repr strings', () => {
        const event = createEvent('$ai_generation', {
            $ai_output_choices:
                "[ResponseOutputMessage(id='msg_abc', content=[ResponseOutputText(text='Hello')], role='assistant')]",
        })

        const result = processAiToolCallExtraction(event)

        expect(result.properties!['$ai_tools_called']).toBeUndefined()
        expect(result.properties!['$ai_tool_call_count']).toBeUndefined()
    })
})
