import { PluginEvent } from '@posthog/plugin-scaffold'

import { MAX_TOOLS_PER_EVENT, extractToolCallNames, sanitizeToolName } from './extract-tool-calls'
import { MAX_OUTPUT_CHOICES_LENGTH, processAiToolCallExtraction } from './index'

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

    describe('OpenAI Responses API (flat function_call items)', () => {
        it.each([
            [
                'single function_call item',
                [
                    { type: 'reasoning', id: 'rs_abc', summary: [] },
                    {
                        type: 'function_call',
                        name: 'get_weather',
                        arguments: '{"city":"Montreal"}',
                        call_id: 'call_abc',
                        id: 'fc_abc',
                        status: 'completed',
                    },
                ],
                ['get_weather'],
            ],
            [
                'multiple function_call items mixed with other types',
                [
                    { type: 'reasoning', id: 'rs_abc', summary: [] },
                    { type: 'function_call', name: 'get_weather', call_id: 'call_1' },
                    { type: 'message', content: [{ type: 'output_text', text: 'hello' }] },
                    { type: 'function_call', name: 'search_docs', call_id: 'call_2' },
                ],
                ['get_weather', 'search_docs'],
            ],
        ])('%s', (_description, input, expected) => {
            expect(extractToolCallNames(input)).toEqual(expected)
        })
    })

    describe('unwrapped choices (tool_calls on choice, no message wrapper)', () => {
        it.each([
            [
                'tool_calls directly on choice',
                [
                    {
                        content: '',
                        role: 'assistant',
                        tool_calls: [
                            { function: { arguments: '{}', name: 'get_weather' }, id: 'call_abc', type: 'function' },
                        ],
                    },
                ],
                ['get_weather'],
            ],
            [
                'multiple tool_calls directly on choice',
                [
                    {
                        role: 'assistant',
                        tool_calls: [
                            { function: { name: 'get_weather' }, id: 'call_1', type: 'function' },
                            { function: { name: 'search_docs' }, id: 'call_2', type: 'function' },
                        ],
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

    describe('wrapped choices object (full API response)', () => {
        it('unwraps {choices: [...]} with OpenAI tool_calls', () => {
            const wrapped = {
                choices: [
                    {
                        finish_reason: 'stop',
                        index: 0,
                        message: {
                            tool_calls: [{ type: 'function', function: { name: 'get_weather' } }],
                        },
                    },
                ],
                created: 1234567890,
                model: 'gpt-4',
            }
            expect(extractToolCallNames(wrapped)).toEqual(['get_weather'])
        })

        it('unwraps {choices: [...]} with multiple tool calls', () => {
            const wrapped = {
                choices: [
                    {
                        message: {
                            tool_calls: [
                                { type: 'function', function: { name: 'search' } },
                                { type: 'function', function: { name: 'summarize' } },
                            ],
                        },
                    },
                ],
            }
            expect(extractToolCallNames(wrapped)).toEqual(['search', 'summarize'])
        })

        it('returns empty for wrapped response with no tool calls', () => {
            const wrapped = {
                choices: [
                    {
                        message: { content: 'Hello!', tool_calls: null },
                    },
                ],
            }
            expect(extractToolCallNames(wrapped)).toEqual([])
        })

        it('ignores non-array choices key', () => {
            expect(extractToolCallNames({ choices: 'not an array' })).toEqual([])
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

    describe('tool name sanitization', () => {
        it.each([
            ['trims whitespace', '  get_weather  ', 'get_weather'],
            ['replaces commas with underscores', 'tool,name,here', 'tool_name_here'],
            ['truncates to MAX_TOOL_NAME_LENGTH', 'a'.repeat(250), 'a'.repeat(200)],
            ['handles combined sanitization', '  tool,with,commas  ', 'tool_with_commas'],
        ])('%s', (_desc, input, expected) => {
            const choices = [
                {
                    message: {
                        tool_calls: [{ type: 'function', function: { name: input } }],
                    },
                },
            ]
            expect(extractToolCallNames(choices)).toEqual([expected])
        })

        it('skips blank tool names', () => {
            const choices = [
                {
                    message: {
                        tool_calls: [
                            { type: 'function', function: { name: '   ' } },
                            { type: 'function', function: { name: 'valid_tool' } },
                        ],
                    },
                },
            ]
            expect(extractToolCallNames(choices)).toEqual(['valid_tool'])
        })
    })

    describe('max tools cap', () => {
        it(`caps at ${MAX_TOOLS_PER_EVENT} tools per event`, () => {
            const toolCalls = Array.from({ length: 150 }, (_, i) => ({
                type: 'function',
                function: { name: `tool_${i}` },
            }))
            const choices = [{ message: { tool_calls: toolCalls } }]
            const result = extractToolCallNames(choices)
            expect(result).toHaveLength(MAX_TOOLS_PER_EVENT)
            expect(result[0]).toBe('tool_0')
            expect(result[MAX_TOOLS_PER_EVENT - 1]).toBe(`tool_${MAX_TOOLS_PER_EVENT - 1}`)
        })
    })
})

describe('sanitizeToolName', () => {
    it.each([
        ['normal name', 'get_weather', 'get_weather'],
        ['trims whitespace', '  search  ', 'search'],
        ['replaces commas', 'a,b,c', 'a_b_c'],
        ['truncates long names', 'x'.repeat(300), 'x'.repeat(200)],
        ['returns null for empty', '', null],
        ['returns null for blank', '   ', null],
    ])('%s', (_desc, input, expected) => {
        expect(sanitizeToolName(input)).toBe(expected)
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

        expect(result.properties!['$ai_tools_called']).toBe('get_weather,search_docs')
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

        expect(result.properties!['$ai_tools_called']).toBe('web_search')
        expect(result.properties!['$ai_tool_call_count']).toBe(1)
    })

    it('extracts OpenAI Responses API function_call items', () => {
        const event = createEvent('$ai_generation', {
            $ai_output_choices: [
                { type: 'reasoning', id: 'rs_abc', summary: [] },
                {
                    type: 'function_call',
                    name: 'get_weather',
                    arguments: '{"city":"Montreal"}',
                    call_id: 'call_abc',
                },
            ],
        })

        const result = processAiToolCallExtraction(event)

        expect(result.properties!['$ai_tools_called']).toBe('get_weather')
        expect(result.properties!['$ai_tool_call_count']).toBe(1)
    })

    it('extracts unwrapped tool_calls (no message wrapper)', () => {
        const event = createEvent('$ai_generation', {
            $ai_output_choices: [
                {
                    content: '',
                    role: 'assistant',
                    tool_calls: [
                        { function: { arguments: '{}', name: 'get_weather' }, id: 'call_abc', type: 'function' },
                    ],
                },
            ],
        })

        const result = processAiToolCallExtraction(event)

        expect(result.properties!['$ai_tools_called']).toBe('get_weather')
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

        expect(result.properties!['$ai_tools_called']).toBe('get_weather')
        expect(result.properties!['$ai_tool_call_count']).toBe(1)
    })

    it('extracts from Python repr string (OpenAI Agents SDK)', () => {
        const event = createEvent('$ai_generation', {
            $ai_output_choices:
                "[ResponseFunctionToolCall(arguments='{\"city\":\"Montreal\"}', call_id='call_V2E', name='get_weather', type='function_call')]",
        })

        const result = processAiToolCallExtraction(event)

        expect(result.properties!['$ai_tools_called']).toBe('get_weather')
        expect(result.properties!['$ai_tool_call_count']).toBe(1)
    })

    it('extracts from wrapped {choices: [...]} full API response', () => {
        const event = createEvent('$ai_generation', {
            $ai_output_choices: {
                choices: [
                    {
                        finish_reason: 'stop',
                        index: 0,
                        message: {
                            tool_calls: [
                                { type: 'function', function: { name: 'get_weather' } },
                                { type: 'function', function: { name: 'search_docs' } },
                            ],
                        },
                    },
                ],
                created: 1234567890,
                model: 'gpt-4',
            },
        })

        const result = processAiToolCallExtraction(event)

        expect(result.properties!['$ai_tools_called']).toBe('get_weather,search_docs')
        expect(result.properties!['$ai_tool_call_count']).toBe(2)
    })

    it('extracts from stringified wrapped {choices: [...]} response', () => {
        const event = createEvent('$ai_generation', {
            $ai_output_choices: JSON.stringify({
                choices: [
                    {
                        message: {
                            tool_calls: [{ type: 'function', function: { name: 'web_search' } }],
                        },
                    },
                ],
            }),
        })

        const result = processAiToolCallExtraction(event)

        expect(result.properties!['$ai_tools_called']).toBe('web_search')
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

        expect(result.properties!['$ai_tools_called']).toBe('get_weather')
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
            $ai_tools_called: 'custom_tool',
            $ai_output_choices: [
                {
                    message: {
                        tool_calls: [{ type: 'function', function: { name: 'get_weather' } }],
                    },
                },
            ],
        })

        const result = processAiToolCallExtraction(event)

        expect(result.properties!['$ai_tools_called']).toBe('custom_tool')
    })

    it('sets $ai_tool_call_count from user-provided $ai_tools_called when count is missing', () => {
        const event = createEvent('$ai_generation', {
            $ai_tools_called: 'tool_a,tool_b,tool_c',
        })

        const result = processAiToolCallExtraction(event)

        expect(result.properties!['$ai_tools_called']).toBe('tool_a,tool_b,tool_c')
        expect(result.properties!['$ai_tool_call_count']).toBe(3)
    })

    it('does not override user-provided $ai_tool_call_count', () => {
        const event = createEvent('$ai_generation', {
            $ai_tools_called: 'tool_a,tool_b',
            $ai_tool_call_count: 5,
        })

        const result = processAiToolCallExtraction(event)

        expect(result.properties!['$ai_tool_call_count']).toBe(5)
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

    describe('fast pre-checks for string values', () => {
        it('skips parsing when no tool-call indicators found', () => {
            const event = createEvent('$ai_generation', {
                $ai_output_choices: JSON.stringify([{ message: { content: 'Hello, how can I help?' } }]).replace(
                    /tool_call|tool_use|function_call|"function"/g,
                    'xxxxx'
                ),
            })

            const result = processAiToolCallExtraction(event)

            expect(result.properties!['$ai_tools_called']).toBeUndefined()
        })

        it('skips parsing when string exceeds size limit', () => {
            const hugeString = 'x'.repeat(MAX_OUTPUT_CHOICES_LENGTH + 1)
            const event = createEvent('$ai_generation', {
                $ai_output_choices: hugeString,
            })

            const result = processAiToolCallExtraction(event)

            expect(result.properties!['$ai_tools_called']).toBeUndefined()
        })

        it.each([
            ['tool_calls keyword', 'tool_call'],
            ['tool_use keyword', 'tool_use'],
            ['function_call keyword', 'function_call'],
            ['"function" keyword', '"function"'],
        ])('proceeds with parsing when %s is present', (_desc, indicator) => {
            // Build a string that contains the indicator but isn't valid tool data
            const event = createEvent('$ai_generation', {
                $ai_output_choices: `[{"message": {"content": "mentioned ${indicator} in text"}}]`,
            })

            const result = processAiToolCallExtraction(event)

            // Should attempt parsing (no tool calls found, but parsing was attempted)
            expect(result.properties!['$ai_tools_called']).toBeUndefined()
        })

        it('does not apply pre-checks to non-string (already parsed) values', () => {
            // Object values bypass string pre-checks entirely
            const event = createEvent('$ai_generation', {
                $ai_output_choices: [
                    {
                        message: {
                            tool_calls: [{ type: 'function', function: { name: 'get_weather' } }],
                        },
                    },
                ],
            })

            const result = processAiToolCallExtraction(event)

            expect(result.properties!['$ai_tools_called']).toBe('get_weather')
        })
    })
})
