import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import { RecipeNormalizer } from './normalizer'
import { AnthropicInputMessage, CompatMessage, OpenAICompletionMessage } from './types'
import {
    asString,
    costContextFromProperties,
    costContextFromTrace,
    formatAiErrorForDisplay,
    formatLLMEventTitle,
    formatModelRowLabel,
    getInternalTagName,
    getSessionID,
    getSessionStartTimestamp,
    getTraceStepCount,
    hasCostBreakdown,
    hasStringContentField,
    isEmptyJSONStructure,
    isInternalToolResultUserMessage,
    isInternalTagMessage,
    isTextContentItem,
    isToolResult,
    isToolStepItem,
    looksLikeXml,
    mapEvaluationRunRow,
    parsePartialJSON,
    parseToolArgumentsForDisplay,
    sanitizeTraceUrlSearchParams,
} from './utils'

type EvaluationRunRow = Parameters<typeof mapEvaluationRunRow>[0]

interface EvaluationRunRowOverrides {
    result?: EvaluationRunRow[6]
    applicable?: EvaluationRunRow[8]
    evaluationType?: EvaluationRunRow[9]
    resultType?: EvaluationRunRow[10]
    sentimentLabel?: EvaluationRunRow[11]
    sentimentScore?: EvaluationRunRow[12]
}

function makeEvaluationRunRow({
    result = true,
    applicable = true,
    evaluationType = 'llm_judge',
    resultType = 'boolean',
    sentimentLabel = null,
    sentimentScore = null,
}: EvaluationRunRowOverrides = {}): EvaluationRunRow {
    return [
        'run-1',
        '2026-04-10T12:00:00Z',
        'eval-1',
        'Test Eval',
        'gen-1',
        'trace-1',
        result,
        'Looks good',
        applicable,
        evaluationType,
        resultType,
        sentimentLabel,
        sentimentScore,
    ]
}

describe('mapEvaluationRunRow', () => {
    it('maps sentiment rows without coercing missing boolean results to false', () => {
        const run = mapEvaluationRunRow(
            makeEvaluationRunRow({
                result: null,
                applicable: null,
                evaluationType: 'sentiment',
                resultType: 'sentiment',
                sentimentLabel: 'positive',
                sentimentScore: '0.91',
            })
        )

        expect(run.result).toBeNull()
        expect(run.evaluation_type).toBe('sentiment')
        expect(run.result_type).toBe('sentiment')
        expect(run.sentiment_label).toBe('positive')
        expect(run.sentiment_score).toBe(0.91)
    })

    it('falls back to sentiment result type for older sentiment rows', () => {
        const run = mapEvaluationRunRow(
            makeEvaluationRunRow({
                result: null,
                applicable: null,
                evaluationType: 'sentiment',
                resultType: null,
                sentimentLabel: 'negative',
            })
        )

        expect(run.result_type).toBe('sentiment')
        expect(run.result).toBeNull()
    })

    it('keeps absent boolean results as null instead of false', () => {
        const run = mapEvaluationRunRow(makeEvaluationRunRow({ result: null }))

        expect(run.result).toBeNull()
    })

    it.each([true, 'true', 'True', '1'])('maps explicit pass result %p', (result) => {
        expect(mapEvaluationRunRow(makeEvaluationRunRow({ result })).result).toBe(true)
    })

    it.each([false, 'false', 'False', '0'])('maps explicit fail result %p', (result) => {
        expect(mapEvaluationRunRow(makeEvaluationRunRow({ result })).result).toBe(false)
    })

    it('maps explicitly non-applicable rows to null', () => {
        const run = mapEvaluationRunRow(makeEvaluationRunRow({ result: false, applicable: 'false' }))

        expect(run.result).toBeNull()
        expect(run.applicable).toBe(false)
    })
})

// The recipe-based `RecipeNormalizer` in `./normalizer` is the production code path.
const recipe = new RecipeNormalizer()
const IMPLS = [
    {
        name: 'recipe',
        normalizeMessage: (r: unknown, d: string) => recipe.normalizeMessage(r, d).messages,
        normalizeMessages: (m: unknown, d: string, t?: unknown) => recipe.normalizeMessages(m, d, t).messages,
    },
] as const

describe.each(IMPLS)('AI observability utils [$name]', ({ normalizeMessage, normalizeMessages }) => {
    beforeEach(() => {
        console.warn = jest.fn()
    })

    describe('getSessionStartTimestamp', () => {
        it.each([
            ['2024-01-15T12:00:00Z', '2024-01-14T12:00:00Z'],
            ['2024-01-01T00:00:00Z', '2023-12-31T00:00:00Z'],
            ['2024-03-01T06:30:00Z', '2024-02-29T06:30:00Z'],
        ])('subtracts 24 hours from %s to get %s', (input, expected) => {
            expect(getSessionStartTimestamp(input)).toBe(expected)
        })
    })

    describe('sanitizeTraceUrlSearchParams', () => {
        it.each([
            [
                {
                    date_from: '-30d',
                    event: 'event-id',
                    timestamp: '2026-01-29T22:07:59Z',
                    exception_ts: '2026-01-29T22:07:59Z',
                    line: '5',
                    tab: 'conversation',
                    back_to: 'traces',
                    filters: [{ key: '$ai_model', value: ['gpt-4o'] }],
                    search: 'foo',
                },
                {},
                {
                    date_from: '-30d',
                    filters: [{ key: '$ai_model', value: ['gpt-4o'] }],
                    search: 'foo',
                },
            ],
            [
                {
                    date_from: '-30d',
                    event: 'event-id',
                    search: 'foo',
                    back_to: 'generations',
                },
                { removeSearch: true },
                { date_from: '-30d' },
            ],
        ])('removes trace-scoped URL params', (searchParams, options, expected) => {
            expect(sanitizeTraceUrlSearchParams(searchParams, options)).toEqual(expected)
        })
    })

    describe('normalizeOutputMessage', () => {
        it('parses OpenAI message', () => {
            const message: OpenAICompletionMessage = {
                role: 'assistant',
                content: 'Hello, world!',
            }
            expect(normalizeMessage(message, 'user')).toEqual([
                {
                    role: 'assistant',
                    content: 'Hello, world!',
                },
            ])
        })

        it('stringifies incomplete OpenAI message', () => {
            const message = {
                role: 'assistant',
            }
            expect(normalizeMessage(message, 'user')).toEqual([
                {
                    role: 'assistant',
                    content: JSON.stringify(message),
                },
            ])

            expect(normalizeMessage(message, 'assistant')).toEqual([
                {
                    role: 'assistant',
                    content: JSON.stringify(message),
                },
            ])
        })

        it('parses OpenAI tool calls', () => {
            const message = {
                role: 'assistant',
                content: '',
                tool_calls: [
                    {
                        type: 'function',
                        id: '123',
                        function: {
                            name: 'test',
                            arguments: '{"foo": "bar"}',
                        },
                    },
                    {
                        type: 'function',
                        id: '456',
                        function: {
                            name: 'test2',
                            arguments: '{"bar": "baz"}',
                        },
                    },
                ],
            }
            expect(normalizeMessage(message, 'user')).toEqual([
                {
                    role: 'assistant',
                    content: '',
                    tool_calls: [
                        {
                            type: 'function',
                            id: '123',
                            function: {
                                name: 'test',
                                arguments: { foo: 'bar' },
                            },
                        },
                        {
                            type: 'function',
                            id: '456',
                            function: {
                                name: 'test2',
                                arguments: { bar: 'baz' },
                            },
                        },
                    ],
                },
            ])
        })

        it('parses OpenAI tool use', () => {
            const message = {
                role: 'tool',
                content: 'response',
                tool_call_id: '456',
            }

            expect(normalizeMessage(message, 'user')).toEqual([
                {
                    role: 'tool',
                    content: 'response',
                    tool_call_id: '456',
                },
            ])
        })

        it('parses a string message', () => {
            expect(normalizeMessage('foo', 'user')).toEqual([
                {
                    role: 'user',
                    content: 'foo',
                },
            ])

            expect(normalizeMessage('foo', 'assistant')).toEqual([
                {
                    role: 'assistant',
                    content: 'foo',
                },
            ])
        })

        it('parses an Anthropic tool call message', () => {
            let message: any = {
                type: 'tool_use',
                id: 'toolu_01D7FLrfh4GYq7yT1ULFeyMV',
                name: 'get_stock_price',
                input: { ticker: '^GSPC' },
            }

            expect(normalizeMessage(message, 'assistant')).toEqual([
                {
                    role: 'assistant',
                    content: '',
                    tool_calls: [
                        {
                            type: 'function',
                            id: 'toolu_01D7FLrfh4GYq7yT1ULFeyMV',
                            function: {
                                name: 'get_stock_price',
                                arguments: { ticker: '^GSPC' },
                            },
                        },
                    ],
                },
            ])

            message = {
                role: 'assistant',
                content: [
                    {
                        type: 'tool_use',
                        id: 'toolu_01D7FLrfh4GYq7yT1ULFeyMV',
                        name: 'get_stock_price',
                        input: { ticker: '^GSPC' },
                    },
                    {
                        type: 'tool_use',
                        id: 'toolu_01D7FLrfh4GYq7yT1ULFeyMV2',
                        name: 'get_stock_price',
                        input: { ticker: '^GSPC' },
                    },
                ],
            }

            expect(normalizeMessage(message, 'assistant')).toEqual([
                {
                    role: 'assistant',
                    content: '',
                    tool_calls: [
                        {
                            type: 'function',
                            id: 'toolu_01D7FLrfh4GYq7yT1ULFeyMV',
                            function: {
                                name: 'get_stock_price',
                                arguments: { ticker: '^GSPC' },
                            },
                        },
                    ],
                },
                {
                    role: 'assistant',
                    content: '',
                    tool_calls: [
                        {
                            type: 'function',
                            id: 'toolu_01D7FLrfh4GYq7yT1ULFeyMV2',
                            function: {
                                name: 'get_stock_price',
                                arguments: { ticker: '^GSPC' },
                            },
                        },
                    ],
                },
            ])
        })

        it('prefers top-level tool_calls over content tool_use blocks', () => {
            // This is the format produced by LangChain's Anthropic callback
            // content has raw Anthropic format with empty input (streaming artifact)
            // tool_calls has the normalized OpenAI format with correct arguments
            const message = {
                role: 'assistant',
                content: [
                    { type: 'text', text: 'Let me check that.' },
                    {
                        type: 'tool_use',
                        id: 'toolu_123',
                        name: 'get_weather',
                        input: {}, // Empty - streaming artifact
                    },
                ],
                tool_calls: [
                    {
                        type: 'function',
                        id: 'toolu_123',
                        function: {
                            name: 'get_weather',
                            arguments: '{"location": "San Francisco"}', // Correct arguments
                        },
                    },
                ],
            }

            const result = normalizeMessage(message, 'assistant')

            // Should use the tool_calls array, not extract from content
            expect(result).toHaveLength(2)
            expect(result[0]).toEqual({
                role: 'assistant',
                content: 'Let me check that.',
            })
            expect(result[1]).toEqual({
                role: 'assistant',
                content: '',
                tool_calls: [
                    {
                        type: 'function',
                        id: 'toolu_123',
                        function: {
                            name: 'get_weather',
                            arguments: { location: 'San Francisco' },
                        },
                    },
                ],
            })
        })

        it('parses an Anthropic tool result message', () => {
            let message: AnthropicInputMessage = {
                role: 'user',
                content: [
                    {
                        type: 'tool_result',
                        tool_use_id: '1',
                        content: 'foo',
                    },
                ],
            }

            expect(normalizeMessage(message, 'user')).toEqual([
                {
                    role: 'assistant (tool result)',
                    content: 'foo',
                    tool_call_id: '1',
                },
            ])

            message = {
                role: 'user',
                content: [
                    {
                        type: 'tool_result',
                        tool_use_id: '1',
                        content: [
                            {
                                type: 'text',
                                text: 'foo',
                            },
                        ],
                    },
                ],
            }
            expect(normalizeMessage(message, 'user')).toEqual([
                {
                    role: 'assistant (tool result)',
                    content: 'foo',
                    tool_call_id: '1',
                },
            ])
        })
    })

    describe('OpenAI Responses API', () => {
        it('parses a function_call item as an assistant tool call', () => {
            const message = {
                type: 'function_call',
                call_id: 'call_tLji37A7lp7Buy7hcqUPMUXE',
                name: 'search_category',
                arguments: '{"dimensions":[],"list_all":true}',
            }

            expect(normalizeMessage(message, 'user')).toEqual([
                {
                    role: 'assistant',
                    content: '',
                    tool_calls: [
                        {
                            type: 'function',
                            id: 'call_tLji37A7lp7Buy7hcqUPMUXE',
                            function: {
                                name: 'search_category',
                                arguments: { dimensions: [], list_all: true },
                            },
                        },
                    ],
                },
            ])
        })

        it('parses a function_call_output item as a tool result', () => {
            const message = {
                type: 'function_call_output',
                call_id: 'call_tLji37A7lp7Buy7hcqUPMUXE',
                output: '{"categories":[{"id":"149288","name":"Asheville Cloud Shaker"}]}',
            }

            expect(normalizeMessage(message, 'user')).toEqual([
                {
                    role: 'assistant (tool result)',
                    content: '{"categories":[{"id":"149288","name":"Asheville Cloud Shaker"}]}',
                    tool_call_id: 'call_tLji37A7lp7Buy7hcqUPMUXE',
                },
            ])
        })

        it('parses a reasoning item as assistant thinking', () => {
            const message = {
                type: 'reasoning',
                id: 'rs_123',
                summary: [
                    { type: 'summary_text', text: 'Thinking about the query...' },
                    { type: 'summary_text', text: 'Deciding on a response.' },
                ],
            }

            expect(normalizeMessage(message, 'user')).toEqual([
                {
                    role: 'assistant (thinking)',
                    content: 'Thinking about the query...\nDeciding on a response.',
                },
            ])
        })

        it('handles reasoning with no summary', () => {
            const message = {
                type: 'reasoning',
                id: 'rs_456',
            }

            expect(normalizeMessage(message, 'user')).toEqual([
                {
                    role: 'assistant (thinking)',
                    content: '',
                },
            ])
        })

        it('handles Vercel AI SDK reasoning with text field', () => {
            const message = {
                type: 'reasoning',
                text: 'Let me think about this step by step.',
            }

            expect(normalizeMessage(message, 'user')).toEqual([
                {
                    role: 'assistant (thinking)',
                    content: 'Let me think about this step by step.',
                },
            ])
        })

        it.each([
            [
                'string arguments (posthog-node format)',
                {
                    type: 'tool-call',
                    id: 'toolu_vrtx_01CTHfH7tfd2vNWSWJhKzfov',
                    function: { name: 'queryModel', arguments: '{"query": "relevant data"}' },
                },
                'toolu_vrtx_01CTHfH7tfd2vNWSWJhKzfov',
                'queryModel',
                { query: 'relevant data' },
            ],
            [
                'object arguments (posthog-node format)',
                {
                    type: 'tool-call',
                    id: 'call_123',
                    function: { name: 'get_weather', arguments: { location: 'NYC' } },
                },
                'call_123',
                'get_weather',
                { location: 'NYC' },
            ],
            [
                'native Vercel SDK format (toolName/input/toolCallId)',
                { type: 'tool-call', toolCallId: 'tc_native_123', toolName: 'get_weather', input: { location: 'NYC' } },
                'tc_native_123',
                'get_weather',
                { location: 'NYC' },
            ],
        ])('handles Vercel AI SDK tool-call with %s', (_label, message, expectedId, expectedName, expectedArgs) => {
            expect(normalizeMessage(message, 'assistant')).toEqual([
                {
                    role: 'assistant',
                    content: '',
                    tool_calls: [
                        {
                            type: 'function',
                            id: expectedId,
                            function: { name: expectedName, arguments: expectedArgs },
                        },
                    ],
                },
            ])
        })

        it.each([
            [
                'object output',
                {
                    type: 'tool-result',
                    toolCallId: 'tc_123',
                    toolName: 'get_weather',
                    output: { temperature: 72, unit: 'F' },
                },
                '{"temperature":72,"unit":"F"}',
                'tc_123',
            ],
            [
                'string output',
                { type: 'tool-result', toolCallId: 'tc_456', toolName: 'search', output: 'Found 3 results' },
                'Found 3 results',
                'tc_456',
            ],
        ])('handles Vercel AI SDK tool-result with %s', (_label, message, expectedContent, expectedToolCallId) => {
            expect(normalizeMessage(message, 'assistant')).toEqual([
                {
                    role: 'assistant (tool result)',
                    content: expectedContent,
                    tool_call_id: expectedToolCallId,
                },
            ])
        })

        it('handles Vercel AI SDK toolName variant with string input', () => {
            const message = { type: 'tool-call', toolCallId: 'tc_1', toolName: 'run_code', input: 'print("hi")' }
            expect(normalizeMessage(message, 'assistant')).toEqual([
                {
                    role: 'assistant',
                    content: '',
                    tool_calls: [
                        {
                            type: 'function',
                            id: 'tc_1',
                            function: { name: 'run_code', arguments: 'print("hi")' },
                        },
                    ],
                },
            ])
        })

        it('handles Vercel AI SDK toolName variant with missing input', () => {
            const message = { type: 'tool-call', toolCallId: 'tc_2', toolName: 'no_args_tool' }
            expect(normalizeMessage(message, 'assistant')).toEqual([
                {
                    role: 'assistant',
                    content: '',
                    tool_calls: [
                        {
                            type: 'function',
                            id: 'tc_2',
                            function: { name: 'no_args_tool', arguments: {} },
                        },
                    ],
                },
            ])
        })

        it('prefers function variant when both function and toolName are present', () => {
            const message = {
                type: 'tool-call',
                id: 'func_id',
                function: { name: 'from_function', arguments: '{"a":1}' },
                toolCallId: 'tool_id',
                toolName: 'from_toolName',
                input: { b: 2 },
            }
            expect(normalizeMessage(message, 'assistant')).toEqual([
                {
                    role: 'assistant',
                    content: '',
                    tool_calls: [
                        {
                            type: 'function',
                            id: 'func_id',
                            function: { name: 'from_function', arguments: { a: 1 } },
                        },
                    ],
                },
            ])
        })

        it('handles Vercel AI SDK tool-result with undefined output', () => {
            const message = { type: 'tool-result', toolCallId: 'tc_empty', toolName: 'void_tool' }
            expect(normalizeMessage(message, 'assistant')).toEqual([
                {
                    role: 'assistant (tool result)',
                    content: '',
                    tool_call_id: 'tc_empty',
                },
            ])
        })

        it('handles Vercel AI SDK tool-result with non-serializable output', () => {
            const circular: Record<string, unknown> = { key: 'value' }
            circular.self = circular
            const message = { type: 'tool-result', toolCallId: 'tc_circ', toolName: 'bad_tool', output: circular }
            const result = normalizeMessage(message, 'assistant')
            expect(result).toEqual([
                {
                    role: 'assistant (tool result)',
                    content: '[object Object]',
                    tool_call_id: 'tc_circ',
                },
            ])
        })

        it('handles Vercel AI SDK mixed content array with reasoning + text + tool-call', () => {
            const message = {
                role: 'assistant',
                content: [
                    { type: 'reasoning', text: 'I should use a tool to look up the data.' },
                    { type: 'text', text: 'Let me check that for you.' },
                    {
                        type: 'tool-call',
                        id: 'toolu_vrtx_abc',
                        function: { name: 'queryModel', arguments: '{"query":"data"}' },
                    },
                ],
            }

            expect(normalizeMessage(message, 'user')).toEqual([
                {
                    role: 'assistant (thinking)',
                    content: 'I should use a tool to look up the data.',
                },
                {
                    role: 'assistant',
                    content: 'Let me check that for you.',
                },
                {
                    role: 'assistant',
                    content: '',
                    tool_calls: [
                        {
                            type: 'function',
                            id: 'toolu_vrtx_abc',
                            function: { name: 'queryModel', arguments: { query: 'data' } },
                        },
                    ],
                },
            ])
        })

        it.each([
            [
                'web_search_call',
                'ws_123',
                'web_search_call',
                { action: { type: 'search', query: 'weather today' } },
                {
                    type: 'web_search_call',
                    id: 'ws_123',
                    status: 'completed',
                    action: { type: 'search', query: 'weather today' },
                },
            ],
            [
                'code_interpreter_call',
                'ci_123',
                'code_interpreter_call',
                { code: 'print("hello")' },
                { type: 'code_interpreter_call', id: 'ci_123', status: 'completed', code: 'print("hello")' },
            ],
            [
                'image_generation_call',
                'ig_123',
                'image_generation_call',
                { prompt: 'a red cat' },
                { type: 'image_generation_call', id: 'ig_123', status: 'completed', prompt: 'a red cat' },
            ],
            [
                'mcp_call',
                'mcp_123',
                'search_docs',
                { query: 'pricing' },
                {
                    type: 'mcp_call',
                    id: 'mcp_123',
                    status: 'completed',
                    name: 'search_docs',
                    server_label: 'docs',
                    arguments: '{"query":"pricing"}',
                },
            ],
            [
                'file_search_call',
                'fs_123',
                'file_search_call',
                { queries: ['q1', 'q2'] },
                { type: 'file_search_call', id: 'fs_123', status: 'completed', queries: ['q1', 'q2'] },
            ],
            [
                'computer_call',
                'cc_123',
                'computer_call',
                { action: { type: 'click', x: 10, y: 20 } },
                {
                    type: 'computer_call',
                    id: 'cc_123',
                    status: 'completed',
                    action: { type: 'click', x: 10, y: 20 },
                },
            ],
        ])(
            'parses %s as an assistant tool call preserving metadata',
            (_toolType, toolId, expectedName, expectedArguments, message) => {
                expect(normalizeMessage(message, 'user')).toEqual([
                    {
                        role: 'assistant',
                        content: '',
                        tool_calls: [
                            {
                                type: 'function',
                                id: toolId,
                                function: { name: expectedName, arguments: expectedArguments },
                            },
                        ],
                    },
                ])
            }
        )

        it('handles function_call with unparseable arguments', () => {
            const message = {
                type: 'function_call',
                call_id: 'call_abc',
                name: 'my_func',
                arguments: '{invalid json',
            }

            expect(normalizeMessage(message, 'user')).toEqual([
                {
                    role: 'assistant',
                    content: '',
                    tool_calls: [
                        {
                            type: 'function',
                            id: 'call_abc',
                            function: {
                                name: 'my_func',
                                arguments: '{invalid json',
                            },
                        },
                    ],
                },
            ])
        })
    })

    it('normalizeMessage: lifts function items out of array-based content into tool_calls', () => {
        const message = {
            role: 'assistant',
            content: [
                {
                    type: 'text',
                    text: "I'll check the weather for you.",
                },
                {
                    type: 'function',
                    id: 'call_123',
                    function: {
                        name: 'get_weather',
                        arguments: { location: 'New York City' },
                    },
                },
            ],
        }

        expect(normalizeMessage(message, 'assistant')).toEqual([
            {
                role: 'assistant',
                content: [
                    {
                        type: 'text',
                        text: "I'll check the weather for you.",
                    },
                ],
                tool_calls: [
                    {
                        type: 'function',
                        id: 'call_123',
                        function: {
                            name: 'get_weather',
                            arguments: { location: 'New York City' },
                        },
                    },
                ],
            },
        ])
    })

    describe('normalizeMessage: array-based content with function items', () => {
        it('leaves content empty when every item is a function', () => {
            const message = {
                role: 'assistant',
                content: [
                    {
                        type: 'function',
                        id: 'call_1',
                        function: { name: 'get_weather', arguments: { location: 'Berlin' } },
                    },
                    {
                        type: 'function',
                        id: 'call_2',
                        function: { name: 'search_docs', arguments: { query: 'foo' } },
                    },
                ],
            }

            expect(normalizeMessage(message, 'assistant')).toEqual([
                {
                    role: 'assistant',
                    content: '',
                    tool_calls: [
                        {
                            type: 'function',
                            id: 'call_1',
                            function: { name: 'get_weather', arguments: { location: 'Berlin' } },
                        },
                        {
                            type: 'function',
                            id: 'call_2',
                            function: { name: 'search_docs', arguments: { query: 'foo' } },
                        },
                    ],
                },
            ])
        })

        it.each([
            ['pre-parsed object', { location: 'Berlin', unit: 'celsius' }, { location: 'Berlin', unit: 'celsius' }],
            ['JSON-encoded string', '{"location":"Berlin","unit":"celsius"}', { location: 'Berlin', unit: 'celsius' }],
        ])('parses function arguments provided as %s', (_label, rawArguments, expectedArguments) => {
            const message = {
                role: 'assistant',
                content: [
                    {
                        type: 'function',
                        id: 'call_1',
                        function: { name: 'get_weather', arguments: rawArguments },
                    },
                ],
            }

            expect(normalizeMessage(message, 'assistant')).toEqual([
                {
                    role: 'assistant',
                    content: '',
                    tool_calls: [
                        {
                            type: 'function',
                            id: 'call_1',
                            function: { name: 'get_weather', arguments: expectedArguments },
                        },
                    ],
                },
            ])
        })

        it('lifts function items into tool_calls and keeps non-function items as content', () => {
            const message = {
                role: 'assistant',
                content: [
                    {
                        type: 'function',
                        id: 'fs_1',
                        function: { name: 'file_search', arguments: { queries: ['q'] } },
                    },
                    { type: 'text', text: 'hi' },
                ],
            }

            expect(normalizeMessage(message, 'assistant')).toEqual([
                {
                    role: 'assistant',
                    content: [{ type: 'text', text: 'hi' }],
                    tool_calls: [
                        {
                            type: 'function',
                            id: 'fs_1',
                            function: { name: 'file_search', arguments: { queries: ['q'] } },
                        },
                    ],
                },
            ])
        })
    })

    describe('normalizeMessage: built-in tool call with explicit name', () => {
        it('uses rawMessage.name for mcp_call, not the "mcp_call" type string', () => {
            const message = {
                type: 'mcp_call',
                id: 'mcp_123',
                name: 'search_docs',
                server_label: 'docs',
                arguments: '{"query":"pricing"}',
            }

            expect(normalizeMessage(message, 'user')).toEqual([
                {
                    role: 'assistant',
                    content: '',
                    tool_calls: [
                        {
                            type: 'function',
                            id: 'mcp_123',
                            function: { name: 'search_docs', arguments: { query: 'pricing' } },
                        },
                    ],
                },
            ])
        })
    })

    describe('role preservation in nested content', () => {
        it('preserves assistant role when recursing into nested array content with output_text', () => {
            // This is the bug we fixed - messages with role + array content should preserve the role
            // Now output_text is properly recognized and content is preserved as array
            const message = {
                role: 'assistant',
                content: [
                    {
                        type: 'output_text',
                        text: 'Hello! How can I help you?',
                    },
                ],
            }

            const result = normalizeMessage(message, 'user')

            expect(result).toHaveLength(1)
            expect(result[0].role).toBe('assistant') // Role is preserved!
            expect(result[0].content).toEqual([
                {
                    type: 'output_text',
                    text: 'Hello! How can I help you?',
                },
            ])
        })

        it('preserves system role when recursing into nested array content with output_text', () => {
            const message = {
                role: 'system',
                content: [
                    {
                        type: 'output_text',
                        text: 'You are a helpful assistant.',
                    },
                ],
            }

            const result = normalizeMessage(message, 'user')

            expect(result).toHaveLength(1)
            expect(result[0].role).toBe('system') // Role is preserved!
            expect(result[0].content).toEqual([
                {
                    type: 'output_text',
                    text: 'You are a helpful assistant.',
                },
            ])
        })

        it('preserves role even when defaultRole is different', () => {
            const assistantMessage = {
                role: 'assistant',
                content: [{ type: 'output_text', text: 'Response' }],
            }

            // Even though defaultRole is 'user', the actual role 'assistant' should be preserved
            const result = normalizeMessage(assistantMessage, 'user')

            expect(result).toHaveLength(1)
            expect(result[0].role).toBe('assistant') // Key test: role is preserved despite different defaultRole
            expect(result[0].content).toEqual([{ type: 'output_text', text: 'Response' }])
        })

        it('preserves input_text content type', () => {
            const message = {
                role: 'user',
                content: [{ type: 'input_text', text: 'What is the weather?' }],
            }

            const result = normalizeMessage(message, 'user')

            expect(result).toHaveLength(1)
            expect(result[0].role).toBe('user')
            expect(result[0].content).toEqual([{ type: 'input_text', text: 'What is the weather?' }])
        })

        it('uses defaultRole when message has no role property', () => {
            const messageWithoutRole = {
                type: 'output_text',
                text: 'Some text',
            }

            const result = normalizeMessage(messageWithoutRole, 'assistant')

            expect(result).toHaveLength(1)
            expect(result[0].role).toBe('assistant')
            // Without a role wrapper, output_text falls through to unsupported and gets stringified
            expect(result[0].content).toBe('{"type":"output_text","text":"Some text"}')
        })

        it('handles Anthropic tool result with nested content and overrides role to assistant (tool result)', () => {
            const toolResultMessage = {
                type: 'tool_result',
                tool_use_id: 'tool_123',
                content: [
                    {
                        type: 'text',
                        text: 'Weather is sunny',
                    },
                ],
            }

            const result = normalizeMessage(toolResultMessage, 'tool')

            expect(result).toHaveLength(1)
            expect(result[0].role).toBe('assistant (tool result)')
            expect(result[0].content).toBe('Weather is sunny')
            expect(result[0].tool_call_id).toBe('tool_123')
        })

        it('preserves custom/unknown roles', () => {
            const customRoleMessage = {
                role: 'custom_agent',
                content: [{ type: 'text', text: 'Custom response' }],
            }

            const result = normalizeMessage(customRoleMessage, 'user')

            // Unknown roles should be preserved as-is (lowercased)
            expect(result).toHaveLength(1)
            expect(result[0].role).toBe('custom_agent')
            expect(result[0].content).toEqual([{ type: 'text', text: 'Custom response' }])
        })

        it.each([
            [
                'single text block',
                {
                    role: 'user',
                    content: JSON.stringify([
                        { type: 'text', text: 'lets respond inline to each bot to explain that its fine' },
                    ]),
                },
                [{ type: 'text', text: 'lets respond inline to each bot to explain that its fine' }],
            ],
            ['plain string stays plain', { role: 'user', content: 'plain text' }, 'plain text'],
            ['invalid JSON falls back to raw string', { role: 'user', content: '[not json' }, '[not json'],
            [
                'unknown block types stay as raw string',
                { role: 'user', content: JSON.stringify([{ type: 'schema', definition: { foo: 'bar' } }]) },
                '[{"type":"schema","definition":{"foo":"bar"}}]',
            ],
            ['empty structured array parses as empty array', { role: 'user', content: '[]' }, []],
        ])(
            'handles stringified structured content in OpenAI-compatible messages: %s',
            (_label, message, expectedContent) => {
                const result = normalizeMessage(message, 'user')

                expect(result).toHaveLength(1)
                expect(result[0].role).toBe('user')
                expect(result[0].content).toEqual(expectedContent)
            }
        )

        it('handles LiteLLM choice wrapper and preserves nested role', () => {
            const liteLLMChoice = {
                finish_reason: 'stop',
                index: 0,
                message: {
                    role: 'assistant',
                    content: [{ type: 'text', text: 'Response from LiteLLM' }],
                },
            }

            const result = normalizeMessage(liteLLMChoice, 'user')

            expect(result).toHaveLength(1)
            expect(result[0].role).toBe('assistant')
            expect(result[0].content).toEqual([{ type: 'text', text: 'Response from LiteLLM' }])
        })
    })

    describe('parsePartialJSON', () => {
        it.each([
            ['full object', '{"key": "value", "n": 42}', { key: 'value', n: 42 }],
            ['full array', '[1, 2, 3]', [1, 2, 3]],
            ['truncated object', '{"key": "value", "long_field": "some te', { key: 'value', long_field: 'some te' }],
            ['truncated nested object', '{"a": {"b": "c", "d": "efg', { a: { b: 'c', d: 'efg' } }],
            ['truncated array', '[1, 2, "hel', [1, 2, 'hel']],
            ['truncated string value', '"hello wor', 'hello wor'],
        ])('%s', (_label, input, expected) => {
            expect(parsePartialJSON(input)).toEqual(expected)
        })

        it('throws on completely invalid input', () => {
            expect(() => parsePartialJSON('not json at all')).toThrow()
        })

        it.each([
            ['bracket-prefixed text', '[Thinking: The user wants to build a todo app.]I will build it'],
            ['bracket-prefixed with tool call', '[Tool Call: lov-write, Input: {"file_path":"src/index.tsx"}]'],
        ])('returns empty array for %s (not actual JSON)', (_label, input) => {
            // These strings start with "[" so they look like JSON arrays,
            // but the partial parser can't extract any valid elements
            const result = parsePartialJSON(input)
            expect(result).toEqual([])
        })
    })

    describe('looksLikeXml', () => {
        it('detects basic XML structures', () => {
            expect(looksLikeXml('<root><child/></root>')).toBe(true)
            expect(looksLikeXml('<?xml version="1.0"?><root></root>')).toBe(true)
            expect(looksLikeXml('<root attr="1">text</root>')).toBe(true)
            expect(looksLikeXml('<self-closing/>')).toBe(true)
        })

        it('returns true for typical HTML snippets (by design)', () => {
            expect(looksLikeXml('<!DOCTYPE html><html><body></body></html>')).toBe(true)
            expect(looksLikeXml('<div class="x">hi</div>')).toBe(true)
        })

        it('returns false for non-XML-like strings', () => {
            expect(looksLikeXml('a < b and c > d')).toBe(false)
            expect(looksLikeXml('plain text')).toBe(false)
            expect(looksLikeXml('{"foo":"bar"}')).toBe(false)
        })
    })

    describe('getInternalTagName / isInternalTagMessage', () => {
        // The shape these tests pin: typed-parts content with a single text item
        // whose entire body is a balanced internal tag wrapper.
        const typedParts = (text: string): CompatMessage['content'] =>
            [{ type: 'text', text }] as unknown as CompatMessage['content']

        it.each<[name: string, body: string, expected: string]>([
            // String content
            ['flat string with system-reminder (kebab)', '<system-reminder>foo</system-reminder>', 'system-reminder'],
            ['flat string with system_reminder (snake)', '<system_reminder>foo</system_reminder>', 'system_reminder'],
            [
                'flat string with system_reminder_message',
                '<system_reminder_message>foo</system_reminder_message>',
                'system_reminder_message',
            ],
            [
                'flat string with attached_context',
                '<attached_context>foo bar baz</attached_context>',
                'attached_context',
            ],
            ['flat string with voice_mode', '<voice_mode>off</voice_mode>', 'voice_mode'],
            [
                'multi-line internal tag body',
                '<system_reminder>\nyou are an agent\nmode: foo\n</system_reminder>',
                'system_reminder',
            ],
            ['leading/trailing whitespace tolerated', '   \n<voice_mode>off</voice_mode>\n  ', 'voice_mode'],
        ])('returns the tag name for: %s', (_, body, expected) => {
            const message: CompatMessage = { role: 'user', content: body }
            expect(getInternalTagName(message)).toBe(expected)
            expect(isInternalTagMessage(message)).toBe(true)
        })

        it('matches the typed-parts shape (single text item)', () => {
            const message: CompatMessage = {
                role: 'user',
                content: typedParts('<system_reminder>be concise</system_reminder>'),
            }
            expect(getInternalTagName(message)).toBe('system_reminder')
        })

        it('matches the {type, content: string} wrapper shape (Vercel SDK legacy)', () => {
            const message: CompatMessage = {
                role: 'user',
                content: {
                    type: 'text',
                    content: '<system-reminder>foo</system-reminder>',
                } as unknown as CompatMessage['content'],
            }
            expect(getInternalTagName(message)).toBe('system-reminder')
        })

        // ---- negative cases: role gate ----

        it('returns undefined for an assistant-role message even with an internal tag wrapper', () => {
            // Models can legitimately emit `<system_reminder>` in their reply. Don't hide.
            const message: CompatMessage = {
                role: 'assistant',
                content: '<system_reminder>foo</system_reminder>',
            }
            expect(getInternalTagName(message)).toBeUndefined()
        })

        it('returns undefined for a system-role message (system messages are filtered upstream anyway)', () => {
            const message: CompatMessage = {
                role: 'system',
                content: '<system_reminder>foo</system_reminder>',
            }
            expect(getInternalTagName(message)).toBeUndefined()
        })

        // ---- negative cases: allowlist gate ----

        it.each<[name: string, body: string]>([
            ['unrelated tag <thinking> — model may emit as visible content', '<thinking>let me think</thinking>'],
            ['unrelated tag <summary>', '<summary>the user wants X</summary>'],
            ['unrelated tag <analysis>', '<analysis>foo</analysis>'],
            ['unrelated tag <reasoning>', '<reasoning>foo</reasoning>'],
            ['unrelated tag <answer>', '<answer>The capital of France is Paris.</answer>'],
            ['unrelated tag not in allowlist', '<useful-context>foo</useful-context>'],
            ['unrelated tag <relevance-scores>', '<relevance-scores>0.9</relevance-scores>'],
            ['generic single-word <task>', '<task>foo</task>'],
            ['HTML structural <pre>', '<pre>code block</pre>'],
            ['HTML structural <code>', '<code>print("hi")</code>'],
        ])('returns undefined for non-allowlisted tag: %s', (_, body) => {
            const message: CompatMessage = { role: 'user', content: body }
            expect(getInternalTagName(message)).toBeUndefined()
            expect(isInternalTagMessage(message)).toBe(false)
        })

        // ---- negative cases: shape gate ----

        it('returns undefined when text content has leading text before the wrapper', () => {
            // User wrote actual text alongside a wrapper-shaped substring. Don't hide.
            const message: CompatMessage = {
                role: 'user',
                content: 'foo <system_reminder>bar</system_reminder>',
            }
            expect(getInternalTagName(message)).toBeUndefined()
        })

        it('returns undefined when text content has trailing text after the wrapper', () => {
            const message: CompatMessage = {
                role: 'user',
                content: '<system_reminder>foo</system_reminder> bar',
            }
            expect(getInternalTagName(message)).toBeUndefined()
        })

        it('returns undefined when content has two sibling wrappers (multi-block, not single)', () => {
            const message: CompatMessage = {
                role: 'user',
                content: '<system_reminder>foo</system_reminder>\n<voice_mode>off</voice_mode>',
            }
            // Conservative — coalescing multi-wrapper bodies is out of scope.
            expect(getInternalTagName(message)).toBeUndefined()
        })

        it('returns undefined for typed-parts with more than one item', () => {
            // Two text items, even if each is itself an internal tag wrapper. The renderer
            // would lose information if we collapsed this; keep it visible.
            const message: CompatMessage = {
                role: 'user',
                content: [
                    { type: 'text', text: '<system_reminder>foo</system_reminder>' },
                    { type: 'text', text: '<voice_mode>off</voice_mode>' },
                ] as unknown as CompatMessage['content'],
            }
            expect(getInternalTagName(message)).toBeUndefined()
        })

        it('returns undefined for typed-parts with a non-text item (image, tool_use, …)', () => {
            const message: CompatMessage = {
                role: 'user',
                content: [{ type: 'image_url', image_url: { url: 'x' } }] as unknown as CompatMessage['content'],
            }
            expect(getInternalTagName(message)).toBeUndefined()
        })

        // ---- negative cases: case-sensitivity + tag-mismatch guards ----

        it('returns undefined for uppercase tag names (internal tags are lowercase by convention)', () => {
            const message: CompatMessage = { role: 'user', content: '<System_Reminder>foo</System_Reminder>' }
            expect(getInternalTagName(message)).toBeUndefined()
        })

        it('returns undefined when open and close tag names differ', () => {
            // Malformed XML — the backref enforces consistency.
            const message: CompatMessage = {
                role: 'user',
                content: '<system_reminder>foo</voice_mode>',
            }
            expect(getInternalTagName(message)).toBeUndefined()
        })

        it('returns undefined for empty content', () => {
            expect(getInternalTagName({ role: 'user', content: '' })).toBeUndefined()
            expect(getInternalTagName({ role: 'user', content: [] })).toBeUndefined()
            expect(getInternalTagName({ role: 'user', content: null as unknown as string })).toBeUndefined()
        })

        it('handles typed-parts content with a multi-line attached_context wrapper', () => {
            const message: CompatMessage = {
                role: 'user',
                content: typedParts('<attached_context>\nfoo\n\nbar: baz\nqux: 123\n</attached_context>'),
            }
            expect(getInternalTagName(message)).toBe('attached_context')
        })
    })

    describe('isToolResult', () => {
        it.each<[name: string, item: unknown]>([
            ['Anthropic typed tool_result', { type: 'tool_result', tool_use_id: 'toolu_1', content: 'ok' }],
            [
                'Vercel SDK tool-result',
                { type: 'tool-result', toolCallId: 'a', toolName: 'search_docs', output: { ok: true } },
            ],
            [
                'OpenAI Responses function_call_output',
                { type: 'function_call_output', call_id: 'c1', output: 'opaque' },
            ],
            [
                'custom {type:"function", tool_name, content}',
                { type: 'function', tool_name: 'lookup', content: 'opaque' },
            ],
        ])('returns true for: %s', (_, item) => {
            expect(isToolResult(item)).toBe(true)
        })

        it.each<[name: string, item: unknown]>([
            ['plain text part', { type: 'text', text: 'hi' }],
            ['Anthropic tool_use (a tool CALL, not a result)', { type: 'tool_use', id: 't1', name: 'x', input: {} }],
            [
                'OpenAI tool CALL with nested function object',
                { type: 'function', function: { name: 'get_weather', arguments: '{}' } },
            ],
            ['Vercel SDK tool-call', { type: 'tool-call', toolCallId: 'a', toolName: 'x', input: {} }],
            ['image part', { type: 'image_url', image_url: { url: 'x' } }],
            ['null', null],
            ['plain string', 'hello'],
            ['function-typed item without tool_name', { type: 'function' }],
        ])('returns false for: %s', (_, item) => {
            expect(isToolResult(item)).toBe(false)
        })
    })

    describe('isInternalToolResultUserMessage', () => {
        it('returns true for a user message whose content is only typed tool_result parts', () => {
            const message: CompatMessage = {
                role: 'user',
                content: [
                    { type: 'tool_result', tool_use_id: 't1', content: 'value-1' },
                    { type: 'tool_result', tool_use_id: 't2', content: 'value-2' },
                ] as unknown as CompatMessage['content'],
            }
            expect(isInternalToolResultUserMessage(message)).toBe(true)
        })

        it('returns true for the custom `{type:"function", tool_name, content}` shape', () => {
            const message: CompatMessage = {
                role: 'user',
                content: [
                    { type: 'function', tool_name: 'lookup', content: 'opaque' },
                ] as unknown as CompatMessage['content'],
            }
            expect(isInternalToolResultUserMessage(message)).toBe(true)
        })

        it('returns false when a tool-result part sits alongside real user text', () => {
            // Hiding would drop the user's prose.
            const message: CompatMessage = {
                role: 'user',
                content: [
                    { type: 'tool_result', tool_use_id: 't1', content: 'value' },
                    { type: 'text', text: 'and please summarize the above' },
                ] as unknown as CompatMessage['content'],
            }
            expect(isInternalToolResultUserMessage(message)).toBe(false)
        })

        it('returns false for an empty content array', () => {
            expect(isInternalToolResultUserMessage({ role: 'user', content: [] })).toBe(false)
        })

        it('returns false for an assistant-role message even if its content is tool-result-shaped', () => {
            const message: CompatMessage = {
                role: 'assistant',
                content: [
                    { type: 'tool_result', tool_use_id: 't1', content: 'value' },
                ] as unknown as CompatMessage['content'],
            }
            expect(isInternalToolResultUserMessage(message)).toBe(false)
        })

        it('returns false for a flat-string user message (text body, not a parts list)', () => {
            expect(isInternalToolResultUserMessage({ role: 'user', content: 'follow-up question' })).toBe(false)
        })
    })

    describe('formatLLMEventTitle', () => {
        it('formats LLMTrace with traceName', () => {
            const trace: LLMTrace = {
                id: 'trace-1',
                createdAt: '2024-01-01T00:00:00Z',
                distinctId: 'user-1',
                traceName: 'My Custom Trace',
                person: {
                    uuid: 'person-1',
                    created_at: '2024-01-01T00:00:00Z',
                    properties: {},
                    distinct_id: 'user-1',
                },
                events: [],
            }
            expect(formatLLMEventTitle(trace)).toBe('My Custom Trace')
        })

        it('formats LLMTrace without traceName', () => {
            const trace: LLMTrace = {
                id: 'trace-1',
                createdAt: '2024-01-01T00:00:00Z',
                distinctId: 'user-1',
                person: {
                    uuid: 'person-1',
                    created_at: '2024-01-01T00:00:00Z',
                    properties: {},
                    distinct_id: 'user-1',
                },
                events: [],
            }
            expect(formatLLMEventTitle(trace)).toBe('Trace')
        })

        describe('$ai_generation events', () => {
            it('formats generation event with span name', () => {
                const event: LLMTraceEvent = {
                    id: 'event-1',
                    event: '$ai_generation',
                    properties: {
                        $ai_span_name: 'Chat Completion',
                        $ai_model: 'gpt-4',
                        $ai_provider: 'openai',
                    },
                    createdAt: '2024-01-01T00:00:00Z',
                }
                expect(formatLLMEventTitle(event)).toBe('Chat Completion')
            })

            it('formats generation event with model and provider', () => {
                const event: LLMTraceEvent = {
                    id: 'event-1',
                    event: '$ai_generation',
                    properties: {
                        $ai_model: 'gpt-4',
                        $ai_provider: 'openai',
                    },
                    createdAt: '2024-01-01T00:00:00Z',
                }
                expect(formatLLMEventTitle(event)).toBe('gpt-4 (openai)')
            })

            it('formats generation event with model only', () => {
                const event: LLMTraceEvent = {
                    id: 'event-1',
                    event: '$ai_generation',
                    properties: {
                        $ai_model: 'gpt-4',
                    },
                    createdAt: '2024-01-01T00:00:00Z',
                }
                expect(formatLLMEventTitle(event)).toBe('gpt-4')
            })

            it('formats generation event without model or provider', () => {
                const event: LLMTraceEvent = {
                    id: 'event-1',
                    event: '$ai_generation',
                    properties: {},
                    createdAt: '2024-01-01T00:00:00Z',
                }
                expect(formatLLMEventTitle(event)).toBe('Generation')
            })
        })

        describe('$ai_embedding events', () => {
            it('formats embedding event with span name', () => {
                const event: LLMTraceEvent = {
                    id: 'event-1',
                    event: '$ai_embedding',
                    properties: {
                        $ai_span_name: 'Document Embedding',
                        $ai_model: 'text-embedding-3-small',
                        $ai_provider: 'openai',
                    },
                    createdAt: '2024-01-01T00:00:00Z',
                }
                expect(formatLLMEventTitle(event)).toBe('Document Embedding')
            })

            it('formats embedding event with model and provider', () => {
                const event: LLMTraceEvent = {
                    id: 'event-1',
                    event: '$ai_embedding',
                    properties: {
                        $ai_model: 'text-embedding-3-small',
                        $ai_provider: 'openai',
                    },
                    createdAt: '2024-01-01T00:00:00Z',
                }
                expect(formatLLMEventTitle(event)).toBe('text-embedding-3-small (openai)')
            })

            it('formats embedding event with model only', () => {
                const event: LLMTraceEvent = {
                    id: 'event-1',
                    event: '$ai_embedding',
                    properties: {
                        $ai_model: 'text-embedding-3-small',
                    },
                    createdAt: '2024-01-01T00:00:00Z',
                }
                expect(formatLLMEventTitle(event)).toBe('text-embedding-3-small')
            })

            it('formats embedding event without model or provider', () => {
                const event: LLMTraceEvent = {
                    id: 'event-1',
                    event: '$ai_embedding',
                    properties: {},
                    createdAt: '2024-01-01T00:00:00Z',
                }
                expect(formatLLMEventTitle(event)).toBe('Embedding')
            })
        })

        describe('$ai_span and other events', () => {
            it('formats span event with span name', () => {
                const event: LLMTraceEvent = {
                    id: 'event-1',
                    event: '$ai_span',
                    properties: {
                        $ai_span_name: 'Database Query',
                    },
                    createdAt: '2024-01-01T00:00:00Z',
                }
                expect(formatLLMEventTitle(event)).toBe('Database Query')
            })

            it('formats span event without span name', () => {
                const event: LLMTraceEvent = {
                    id: 'event-1',
                    event: '$ai_span',
                    properties: {},
                    createdAt: '2024-01-01T00:00:00Z',
                }
                expect(formatLLMEventTitle(event)).toBe('Span')
            })

            it('formats metric event', () => {
                const event: LLMTraceEvent = {
                    id: 'event-1',
                    event: '$ai_metric',
                    properties: {
                        $ai_span_name: 'Performance Metric',
                    },
                    createdAt: '2024-01-01T00:00:00Z',
                }
                expect(formatLLMEventTitle(event)).toBe('Performance Metric')
            })

            it('formats feedback event', () => {
                const event: LLMTraceEvent = {
                    id: 'event-1',
                    event: '$ai_feedback',
                    properties: {
                        $ai_span_name: 'User Feedback',
                    },
                    createdAt: '2024-01-01T00:00:00Z',
                }
                expect(formatLLMEventTitle(event)).toBe('User Feedback')
            })

            it('formats unknown event type', () => {
                const event: LLMTraceEvent = {
                    id: 'event-1',
                    event: 'custom_event',
                    properties: {
                        $ai_span_name: 'Custom Action',
                    },
                    createdAt: '2024-01-01T00:00:00Z',
                }
                expect(formatLLMEventTitle(event)).toBe('Custom Action')
            })
        })

        describe('non-string properties (untyped property bag)', () => {
            // `$ai_*` title properties are strings by convention, but the event property bag is
            // untyped. A structured value (object/array) or number must never be returned verbatim,
            // or it would be rendered as a raw React child and crash the page (React error #31).
            const cases: Array<[string, string, Record<string, unknown>, string]> = [
                [
                    'generation, object span name, with model',
                    '$ai_generation',
                    { $ai_span_name: {}, $ai_model: 'gpt-4' },
                    'gpt-4',
                ],
                ['generation, object span name, no model', '$ai_generation', { $ai_span_name: {} }, 'Generation'],
                ['generation, object model', '$ai_generation', { $ai_model: {} }, 'Generation'],
                [
                    'generation, object model, with provider',
                    '$ai_generation',
                    { $ai_model: {}, $ai_provider: 'openai' },
                    'Generation (openai)',
                ],
                ['generation, object provider', '$ai_generation', { $ai_model: 'gpt-4', $ai_provider: {} }, 'gpt-4'],
                ['embedding, object span name', '$ai_embedding', { $ai_span_name: {} }, 'Embedding'],
                ['embedding, object model', '$ai_embedding', { $ai_model: {} }, 'Embedding'],
                ['span, object span name', '$ai_span', { $ai_span_name: {} }, 'Span'],
                ['span, array span name', '$ai_span', { $ai_span_name: [] }, 'Span'],
                ['span, numeric span name', '$ai_span', { $ai_span_name: 123 }, 'Span'],
            ]

            it.each(cases)('%s falls back to a string label', (_label, event, properties, expected) => {
                const traceEvent: LLMTraceEvent = {
                    id: 'event-1',
                    event,
                    properties,
                    createdAt: '2024-01-01T00:00:00Z',
                }
                const title = formatLLMEventTitle(traceEvent)
                expect(typeof title).toBe('string')
                expect(title).toBe(expected)
            })
        })
    })

    describe('formatModelRowLabel', () => {
        it('returns null for a trace', () => {
            const trace: LLMTrace = {
                id: 'trace-1',
                createdAt: '2024-01-01T00:00:00Z',
                distinctId: 'user-1',
                person: {
                    uuid: 'person-1',
                    created_at: '2024-01-01T00:00:00Z',
                    properties: {},
                    distinct_id: 'user-1',
                },
                events: [],
            }
            expect(formatModelRowLabel(trace)).toBeNull()
        })

        const cases: Array<[string, string, Record<string, unknown>, string | null]> = [
            // Only generations with a span name get a model row; otherwise the event title covers it.
            ['span event', '$ai_span', { $ai_span_name: 'My Span', $ai_model: 'gpt-4' }, null],
            ['embedding event', '$ai_embedding', { $ai_span_name: 'Embed', $ai_model: 'gpt-4' }, null],
            ['generation without span name', '$ai_generation', { $ai_model: 'gpt-4' }, null],
            ['generation with object span name', '$ai_generation', { $ai_span_name: {}, $ai_model: 'gpt-4' }, null],
            [
                'generation with model and provider',
                '$ai_generation',
                { $ai_span_name: 'Chat', $ai_model: 'gpt-4', $ai_provider: 'openai' },
                'gpt-4 (openai)',
            ],
            ['generation with model only', '$ai_generation', { $ai_span_name: 'Chat', $ai_model: 'gpt-4' }, 'gpt-4'],
            [
                'generation with object model and string provider',
                '$ai_generation',
                { $ai_span_name: 'Chat', $ai_model: {}, $ai_provider: 'openai' },
                'openai',
            ],
            [
                'generation with string model and object provider',
                '$ai_generation',
                { $ai_span_name: 'Chat', $ai_model: 'gpt-4', $ai_provider: {} },
                'gpt-4',
            ],
            ['generation with object model only', '$ai_generation', { $ai_span_name: 'Chat', $ai_model: {} }, null],
            ['generation with array model only', '$ai_generation', { $ai_span_name: 'Chat', $ai_model: [] }, null],
            ['generation with numeric model only', '$ai_generation', { $ai_span_name: 'Chat', $ai_model: 4 }, null],
            ['generation without model or provider', '$ai_generation', { $ai_span_name: 'Chat' }, null],
        ]

        it.each(cases)('%s', (_label, event, properties, expected) => {
            const traceEvent: LLMTraceEvent = {
                id: 'event-1',
                event,
                properties,
                createdAt: '2024-01-01T00:00:00Z',
            }
            expect(formatModelRowLabel(traceEvent)).toBe(expected)
        })
    })

    describe('LiteLLM support', () => {
        const litellmChoice = {
            finish_reason: 'stop',
            index: 0,
            message: {
                annotations: [],
                content:
                    "That's wonderful to hear! 😊 I'm here to spread positivity. If you have any questions or need anything, just let me know!",
                function_call: null,
                role: 'assistant',
                tool_calls: null,
            },
            provider_specific_fields: {},
        }

        const litellmResponse = {
            choices: [litellmChoice],
            model: 'gpt-3.5-turbo',
            usage: { prompt_tokens: 10, completion_tokens: 25, total_tokens: 35 },
        }

        describe('normalizeMessage', () => {
            it('should handle LiteLLM choice format', () => {
                const result = normalizeMessage(litellmChoice, 'user')

                expect(result).toHaveLength(1)
                expect(result[0]).toMatchObject({
                    role: 'assistant',
                    content:
                        "That's wonderful to hear! 😊 I'm here to spread positivity. If you have any questions or need anything, just let me know!",
                    function_call: null,
                })
                expect(result[0].tool_calls).toBeUndefined()
            })

            it('should handle LiteLLM choice with tool calls', () => {
                const choiceWithTools = {
                    ...litellmChoice,
                    message: {
                        ...litellmChoice.message,
                        content: null,
                        tool_calls: [
                            {
                                type: 'function',
                                id: 'call_123',
                                function: {
                                    name: 'get_weather',
                                    arguments: '{"location": "San Francisco"}',
                                },
                            },
                        ],
                    },
                }

                const result = normalizeMessage(choiceWithTools, 'user')

                expect(result).toHaveLength(1)
                expect(result[0].role).toBe('assistant')
                expect(result[0].tool_calls).toHaveLength(1)
                expect(result[0].tool_calls![0].function.name).toBe('get_weather')
            })
        })

        describe('normalizeMessages', () => {
            it('should handle LiteLLM response format', () => {
                const result = normalizeMessages(litellmResponse, 'assistant')

                expect(result).toHaveLength(1)
                expect(result[0]).toMatchObject({
                    role: 'assistant',
                    content:
                        "That's wonderful to hear! 😊 I'm here to spread positivity. If you have any questions or need anything, just let me know!",
                    function_call: null,
                })
                expect(result[0].tool_calls).toBeUndefined()
            })

            it('should handle LiteLLM response with multiple choices', () => {
                const multiChoiceResponse = {
                    choices: [
                        litellmChoice,
                        {
                            ...litellmChoice,
                            index: 1,
                            message: {
                                ...litellmChoice.message,
                                content: 'Alternative response',
                            },
                        },
                    ],
                }

                const result = normalizeMessages(multiChoiceResponse, 'assistant')

                expect(result).toHaveLength(2)
                expect(result[0].content).toBe(
                    "That's wonderful to hear! 😊 I'm here to spread positivity. If you have any questions or need anything, just let me know!"
                )
                expect(result[1].content).toBe('Alternative response')
            })

            it('should handle empty LiteLLM response gracefully', () => {
                const emptyResponse = { choices: [] }
                const result = normalizeMessages(emptyResponse, 'assistant')

                expect(result).toHaveLength(0)
            })

            it('returns no messages for undefined input', () => {
                expect(normalizeMessages(undefined, 'assistant')).toEqual([])
            })
        })

        describe('Role normalization', () => {
            it('should preserve system role in array-based content', () => {
                const systemMessage = {
                    role: 'system',
                    content: [{ type: 'text', text: 'You are a helpful assistant.' }],
                }

                const result = normalizeMessage(systemMessage, 'user')

                expect(result).toHaveLength(1)
                expect(result[0].role).toBe('system')
                expect(result[0].content).toEqual([{ type: 'text', text: 'You are a helpful assistant.' }])
            })

            it('should preserve system role in string content', () => {
                const systemMessage = {
                    role: 'system',
                    content: 'You are a helpful assistant.',
                }

                const result = normalizeMessage(systemMessage, 'user')

                expect(result).toHaveLength(1)
                expect(result[0].role).toBe('system')
                expect(result[0].content).toBe('You are a helpful assistant.')
            })

            it('should map known provider roles', () => {
                const humanMessage = {
                    role: 'human',
                    content: 'Hello',
                }

                const result = normalizeMessage(humanMessage, 'user')

                expect(result).toHaveLength(1)
                expect(result[0].role).toBe('user')
                expect(result[0].content).toBe('Hello')
            })
        })
    })

    describe('LangChain/LangGraph format', () => {
        it('normalizeMessage maps human type to user role', () => {
            const message = { type: 'human', content: 'Hello', id: 'msg-1' }
            const result = normalizeMessage(message, 'assistant')
            expect(result).toEqual([{ role: 'user', content: 'Hello' }])
        })

        it('normalizeMessage maps ai type to assistant role', () => {
            const message = { type: 'ai', content: 'Hi there', id: 'msg-2', meta: {} }
            const result = normalizeMessage(message, 'user')
            expect(result).toEqual([{ role: 'assistant', content: 'Hi there' }])
        })

        it('normalizeMessage handles ai type with tool_calls', () => {
            const message = {
                type: 'ai',
                content: '',
                tool_calls: [
                    {
                        type: 'function' as const,
                        id: 'toolu_123',
                        function: { name: 'search', arguments: '{"q":"test"}' },
                    },
                ],
            }
            const result = normalizeMessage(message, 'user')
            expect(result).toHaveLength(1)
            expect(result[0].role).toBe('assistant')
            expect(result[0].tool_calls).toHaveLength(1)
            expect(result[0].tool_calls![0].function.name).toBe('search')
        })

        it('normalizeMessage handles tool type with tool_call_id', () => {
            const message = {
                type: 'tool',
                content: 'Search results: ...',
                tool_call_id: 'toolu_123',
            }
            const result = normalizeMessage(message, 'assistant')
            expect(result).toEqual([{ role: 'assistant', content: 'Search results: ...', tool_call_id: 'toolu_123' }])
        })

        it('normalizeMessage maps context type to system role', () => {
            const message = { type: 'context', content: '<system_reminder>Your initial mode is sql.</system_reminder>' }
            const result = normalizeMessage(message, 'user')
            expect(result).toEqual([
                { role: 'system', content: '<system_reminder>Your initial mode is sql.</system_reminder>' },
            ])
        })
    })

    describe('OTel parts format', () => {
        it('normalizes a single text part into a string content', () => {
            const message = {
                role: 'assistant',
                parts: [{ type: 'text', content: 'Hello from OTel!' }],
            }

            expect(normalizeMessage(message, 'user')).toEqual([{ role: 'assistant', content: 'Hello from OTel!' }])
        })

        it('normalizes multiple text parts into an array content', () => {
            const message = {
                role: 'assistant',
                parts: [
                    { type: 'text', content: 'First part.' },
                    { type: 'text', content: 'Second part.' },
                ],
            }

            expect(normalizeMessage(message, 'user')).toEqual([
                {
                    role: 'assistant',
                    content: [
                        { type: 'text', text: 'First part.' },
                        { type: 'text', text: 'Second part.' },
                    ],
                },
            ])
        })

        it('normalizes tool_call parts into CompatToolCall format', () => {
            const message = {
                role: 'assistant',
                parts: [
                    {
                        type: 'tool_call',
                        id: 'call_1',
                        name: 'get_weather',
                        arguments: { location: 'London' },
                    },
                ],
            }

            expect(normalizeMessage(message, 'user')).toEqual([
                {
                    role: 'assistant',
                    content: '',
                    tool_calls: [
                        {
                            type: 'function',
                            id: 'call_1',
                            function: {
                                name: 'get_weather',
                                arguments: { location: 'London' },
                            },
                        },
                    ],
                },
            ])
        })

        it('handles mixed text and tool_call parts', () => {
            const message = {
                role: 'assistant',
                parts: [
                    { type: 'text', content: 'Let me check that.' },
                    {
                        type: 'tool_call',
                        id: 'call_1',
                        name: 'get_weather',
                        arguments: { location: 'London' },
                    },
                ],
            }

            expect(normalizeMessage(message, 'user')).toEqual([
                {
                    role: 'assistant',
                    content: 'Let me check that.',
                    tool_calls: [
                        {
                            type: 'function',
                            id: 'call_1',
                            function: {
                                name: 'get_weather',
                                arguments: { location: 'London' },
                            },
                        },
                    ],
                },
            ])
        })

        it('preserves top-level fields via spread', () => {
            const message = {
                role: 'assistant',
                finish_reason: 'stop',
                parts: [{ type: 'text', content: 'Done.' }],
            }

            expect(normalizeMessage(message, 'user')).toEqual([
                { role: 'assistant', finish_reason: 'stop', content: 'Done.' },
            ])
        })

        it('handles tool_call without id', () => {
            const message = {
                role: 'assistant',
                parts: [
                    {
                        type: 'tool_call',
                        name: 'do_thing',
                        arguments: { x: 1 },
                    },
                ],
            }

            const result = normalizeMessage(message, 'user')
            expect(result[0].tool_calls![0].id).toBeUndefined()
            expect(result[0].tool_calls![0].function.name).toBe('do_thing')
        })

        it('handles tool_call without arguments', () => {
            const message = {
                role: 'assistant',
                parts: [{ type: 'tool_call', id: 'call_1', name: 'no_args' }],
            }

            const result = normalizeMessage(message, 'user')
            expect(result[0].tool_calls![0].function.arguments).toEqual({})
        })

        it('normalizes role aliases', () => {
            const message = {
                role: 'human',
                parts: [{ type: 'text', content: 'Hi' }],
            }

            expect(normalizeMessage(message, 'assistant')).toEqual([{ role: 'user', content: 'Hi' }])
        })

        it('normalizes tool_call_response parts into tool messages', () => {
            const message = {
                role: 'user',
                parts: [
                    {
                        type: 'tool_call_response',
                        id: 'call_abc',
                        name: 'get_weather',
                        result: 'Sunny, 25°C',
                    },
                ],
            }

            expect(normalizeMessage(message, 'user')).toEqual([
                { role: 'tool', content: 'Sunny, 25°C', tool_call_id: 'call_abc' },
            ])
        })

        it('stringifies non-string tool_call_response results', () => {
            const message = {
                role: 'user',
                parts: [
                    {
                        type: 'tool_call_response',
                        id: 'call_1',
                        name: 'get_data',
                        result: { temperature: 25, unit: 'C' },
                    },
                ],
            }

            expect(normalizeMessage(message, 'user')).toEqual([
                {
                    role: 'tool',
                    content: '{"temperature":25,"unit":"C"}',
                    tool_call_id: 'call_1',
                },
            ])
        })

        it('parses stringified JSON tool_call arguments', () => {
            const message = {
                role: 'assistant',
                parts: [
                    {
                        type: 'tool_call',
                        id: 'call_1',
                        name: 'get_weather',
                        arguments: '{"latitude":45.5,"longitude":-73.5}',
                    },
                ],
            }

            expect(normalizeMessage(message, 'user')).toEqual([
                {
                    role: 'assistant',
                    content: '',
                    tool_calls: [
                        {
                            type: 'function',
                            id: 'call_1',
                            function: {
                                name: 'get_weather',
                                arguments: { latitude: 45.5, longitude: -73.5 },
                            },
                        },
                    ],
                },
            ])
        })

        it('handles a full tool-use conversation', () => {
            const messages = [
                {
                    role: 'assistant',
                    parts: [
                        {
                            type: 'tool_call',
                            id: 'call_1',
                            name: 'get_weather',
                            arguments: '{"location":"Montreal"}',
                        },
                    ],
                    finish_reason: 'tool_call',
                },
                {
                    role: 'user',
                    parts: [
                        {
                            type: 'tool_call_response',
                            id: 'call_1',
                            name: 'get_weather',
                            result: '-10°C, partly cloudy',
                        },
                    ],
                },
            ]

            const result = normalizeMessages(messages, 'user')

            expect(result).toEqual([
                {
                    role: 'assistant',
                    finish_reason: 'tool_call',
                    content: '',
                    tool_calls: [
                        {
                            type: 'function',
                            id: 'call_1',
                            function: { name: 'get_weather', arguments: { location: 'Montreal' } },
                        },
                    ],
                },
                {
                    role: 'tool',
                    content: '-10°C, partly cloudy',
                    tool_call_id: 'call_1',
                },
            ])
        })

        it('handles empty parts array', () => {
            const message = {
                role: 'assistant',
                parts: [],
            }

            expect(normalizeMessage(message, 'user')).toEqual([{ role: 'assistant', content: '' }])
        })
    })

    describe('getSessionID', () => {
        const baseEvent = (overrides: Partial<LLMTraceEvent> = {}): LLMTraceEvent => ({
            id: 'event-id',
            event: '$ai_span',
            properties: {},
            createdAt: '2024-01-01T00:00:00Z',
            ...overrides,
        })

        const baseTrace = (events: LLMTraceEvent[]): LLMTrace => ({
            id: 'trace-id',
            createdAt: '2024-01-01T00:00:00Z',
            distinctId: 'distinct-id',
            person: {
                uuid: 'person-id',
                created_at: '2024-01-01T00:00:00Z',
                properties: {},
                distinct_id: 'distinct-id',
            },
            events,
        })

        it('returns the direct session id when the event has one', () => {
            const event = baseEvent({
                properties: {
                    $session_id: 'session-123',
                },
            })

            expect(getSessionID(event)).toEqual('session-123')
        })

        it('derives session id from children when $ai_trace lacks direct value', () => {
            const traceEvent = baseEvent({
                id: 'trace-event',
                event: '$ai_trace',
                properties: {},
            })
            const childEvents = [
                baseEvent({
                    id: 'child-1',
                    properties: { $session_id: 'session-abc' },
                }),
                baseEvent({
                    id: 'child-2',
                    properties: { $session_id: 'session-abc' },
                }),
            ]

            expect(getSessionID(traceEvent, childEvents)).toEqual('session-abc')
        })

        it('returns null when child session ids conflict', () => {
            const traceEvent = baseEvent({
                id: 'trace-event',
                event: '$ai_trace',
            })
            const childEvents = [
                baseEvent({
                    id: 'child-1',
                    properties: { $session_id: 'session-abc' },
                }),
                baseEvent({
                    id: 'child-2',
                    properties: { $session_id: 'session-def' },
                }),
            ]

            expect(getSessionID(traceEvent, childEvents)).toBeNull()
        })

        it('uses consistent child session id for pseudo traces', () => {
            const childEvents = [
                baseEvent({ id: 'child-1', properties: { $session_id: 'session-xyz' } }),
                baseEvent({ id: 'child-2', properties: { $session_id: 'session-xyz' } }),
            ]
            const trace = baseTrace(childEvents)

            expect(getSessionID(trace)).toEqual('session-xyz')
        })

        it('returns null for pseudo traces with mixed session ids', () => {
            const childEvents = [
                baseEvent({ id: 'child-1', properties: { $session_id: 'session-xyz' } }),
                baseEvent({ id: 'child-2', properties: { $session_id: 'session-abc' } }),
            ]
            const trace = baseTrace(childEvents)

            expect(getSessionID(trace)).toBeNull()
        })
    })

    describe('costContextFromProperties', () => {
        it('returns undefined when $ai_total_cost_usd is absent', () => {
            expect(costContextFromProperties({})).toBeUndefined()
        })

        it('returns undefined when $ai_total_cost_usd is not a number', () => {
            expect(costContextFromProperties({ $ai_total_cost_usd: 'invalid' })).toBeUndefined()
        })

        it('maps all cost properties', () => {
            const props = {
                $ai_input_cost_usd: 0.01,
                $ai_output_cost_usd: 0.02,
                $ai_request_cost_usd: 0.003,
                $ai_web_search_cost_usd: 0.015,
                $ai_total_cost_usd: 0.048,
            }
            expect(costContextFromProperties(props)).toEqual({
                inputCost: 0.01,
                outputCost: 0.02,
                requestCost: 0.003,
                webSearchCost: 0.015,
                totalCost: 0.048,
            })
        })

        it('leaves optional cost fields as undefined when absent', () => {
            const props = { $ai_total_cost_usd: 0.05 }
            const ctx = costContextFromProperties(props)
            expect(ctx).not.toBeUndefined()
            expect(ctx && ctx.totalCost).toBe(0.05)
            expect(ctx && ctx.inputCost).toBeUndefined()
            expect(ctx && ctx.outputCost).toBeUndefined()
            expect(ctx && ctx.requestCost).toBeUndefined()
            expect(ctx && ctx.webSearchCost).toBeUndefined()
        })
    })

    describe('costContextFromTrace', () => {
        it('returns undefined when totalCost is undefined', () => {
            expect(costContextFromTrace({})).toBeUndefined()
        })

        it('maps all trace cost fields', () => {
            const trace = {
                inputCost: 0.01,
                outputCost: 0.02,
                requestCost: 0.003,
                webSearchCost: 0.015,
                totalCost: 0.048,
            }
            expect(costContextFromTrace(trace)).toEqual({
                inputCost: 0.01,
                outputCost: 0.02,
                requestCost: 0.003,
                webSearchCost: 0.015,
                totalCost: 0.048,
            })
        })

        it('handles trace with only totalCost', () => {
            const trace = { totalCost: 0.05 }
            const ctx = costContextFromTrace(trace)
            expect(ctx).not.toBeUndefined()
            expect(ctx && ctx.totalCost).toBe(0.05)
            expect(ctx && ctx.inputCost).toBeUndefined()
        })
    })

    describe('hasCostBreakdown', () => {
        it('returns false when only totalCost is set', () => {
            expect(hasCostBreakdown({ totalCost: 0.05 })).toBe(false)
        })

        it('returns true when inputCost is present', () => {
            expect(hasCostBreakdown({ totalCost: 0.05, inputCost: 0.01 })).toBe(true)
        })

        it('returns true when outputCost is present', () => {
            expect(hasCostBreakdown({ totalCost: 0.05, outputCost: 0.02 })).toBe(true)
        })

        it('returns true when requestCost is positive', () => {
            expect(hasCostBreakdown({ totalCost: 0.05, requestCost: 0.003 })).toBe(true)
        })

        it('returns false when requestCost is zero', () => {
            expect(hasCostBreakdown({ totalCost: 0.05, requestCost: 0 })).toBe(false)
        })

        it('returns true when webSearchCost is positive', () => {
            expect(hasCostBreakdown({ totalCost: 0.05, webSearchCost: 0.01 })).toBe(true)
        })

        it('returns false when webSearchCost is zero', () => {
            expect(hasCostBreakdown({ totalCost: 0.05, webSearchCost: 0 })).toBe(false)
        })

        it('returns true when inputCost is zero (zero is still a valid breakdown)', () => {
            expect(hasCostBreakdown({ totalCost: 0, inputCost: 0 })).toBe(true)
        })
    })

    describe('isEmptyJSONStructure', () => {
        it.each<[string, unknown, boolean]>([
            ['empty object', {}, true],
            ['empty array', [], true],
            ['non-empty object', { a: 1 }, false],
            ['non-empty array', [1], false],
            ['string', 'hi', false],
            ['number', 0, false],
            ['null', null, false],
            ['undefined', undefined, false],
        ])('returns %s -> %s', (_label, value, expected) => {
            expect(isEmptyJSONStructure(value)).toBe(expected)
        })
    })

    describe('parseToolArgumentsForDisplay', () => {
        it('returns empty for null, undefined, and empty string', () => {
            expect(parseToolArgumentsForDisplay(null)).toEqual({ kind: 'empty' })
            expect(parseToolArgumentsForDisplay(undefined)).toEqual({ kind: 'empty' })
            expect(parseToolArgumentsForDisplay('')).toEqual({ kind: 'empty' })
        })

        it('returns empty for empty object and empty array (object form)', () => {
            expect(parseToolArgumentsForDisplay({})).toEqual({ kind: 'empty' })
            expect(parseToolArgumentsForDisplay([])).toEqual({ kind: 'empty' })
        })

        it('returns empty for stringified empty object/array', () => {
            expect(parseToolArgumentsForDisplay('{}')).toEqual({ kind: 'empty' })
            expect(parseToolArgumentsForDisplay('[]')).toEqual({ kind: 'empty' })
        })

        it('returns parsed object for an object input', () => {
            expect(parseToolArgumentsForDisplay({ location: 'SF' })).toEqual({
                kind: 'parsed',
                value: { location: 'SF' },
            })
        })

        it('returns parsed object for stringified JSON object', () => {
            expect(parseToolArgumentsForDisplay('{"location": "Berlin"}')).toEqual({
                kind: 'parsed',
                value: { location: 'Berlin' },
            })
        })

        it('returns raw string when JSON is unparseable', () => {
            expect(parseToolArgumentsForDisplay('{not valid json')).toEqual({
                kind: 'raw',
                value: '{not valid json',
            })
        })

        it('returns raw string when stringified value parses to a non-object scalar', () => {
            // partial-json may parse `"hello"` to the string "hello" — that's not a structured arg payload, fall back.
            expect(parseToolArgumentsForDisplay('"hello"')).toEqual({ kind: 'raw', value: '"hello"' })
        })
    })

    describe('hasStringContentField', () => {
        it.each<[name: string, input: unknown, expected: boolean]>([
            ['accepts {content: "hi"}', { content: 'hi' }, true],
            ['accepts {type: "text", content: "hi"} — extra fields are fine', { type: 'text', content: 'hi' }, true],
            ['accepts {content: ""} — empty string still passes', { content: '' }, true],
            ['rejects {content: 42} — non-string content', { content: 42 }, false],
            ['rejects {content: null}', { content: null }, false],
            ['rejects missing `content` property', { type: 'text' }, false],
            ['rejects null', null, false],
            ['rejects undefined', undefined, false],
            ['rejects a plain string', 'hi', false],
            ['rejects an array', [{ content: 'hi' }], false],
        ])('%s', (_, input, expected) => {
            expect(hasStringContentField(input)).toBe(expected)
        })
    })

    describe('isToolStepItem', () => {
        it.each<[name: string, input: unknown, expected: boolean]>([
            ['accepts Anthropic `tool_use`', { type: 'tool_use', id: 'toolu_1', name: 'x', input: {} }, true],
            ['accepts Vercel SDK `tool-call`', { type: 'tool-call', toolCallId: 'a', toolName: 'x', input: {} }, true],
            ['accepts unified `{type: "function"}`', { type: 'function', function: { name: 'x' } }, true],
            [
                'accepts OpenAI Responses `function_call`',
                { type: 'function_call', call_id: 'c1', name: 'x', arguments: '{}' },
                true,
            ],
            [
                'accepts OpenAI Responses built-in tool call (e.g. web_search_call)',
                { id: 'ws1', type: 'web_search_call', status: 'completed' },
                true,
            ],
            ['accepts Anthropic `tool_result`', { type: 'tool_result', tool_use_id: 'toolu_1', content: 'ok' }, true],
            [
                'accepts Vercel SDK `tool-result`',
                { type: 'tool-result', toolCallId: 'a', toolName: 'search_docs', result: 'ok' },
                true,
            ],
            ['rejects text content items', { type: 'text', text: 'hi' }, false],
            ['rejects image items', { type: 'image_url', image_url: { url: 'x' } }, false],
            ['rejects file items', { type: 'file', file: { filename: 'f', file_data: 'd' } }, false],
            ['rejects null', null, false],
            ['rejects a plain string', 'function', false],
            ['rejects `{type: "function"}` without a `function` payload', { type: 'function' }, false],
            [
                'rejects `{type: "function", function: "not-an-object"}`',
                { type: 'function', function: 'not-an-object' },
                false,
            ],
        ])('%s', (_, input, expected) => {
            expect(isToolStepItem(input)).toBe(expected)
        })
    })

    describe('isTextContentItem', () => {
        it.each<[name: string, input: unknown, expected: boolean]>([
            ['accepts {type: "text", text: "hi"}', { type: 'text', text: 'hi' }, true],
            ['accepts {type: "text", text: ""}', { type: 'text', text: '' }, true],
            ['rejects missing `text` property', { type: 'text' }, false],
            ['rejects wrong `type` literal', { type: 'image', text: 'hi' }, false],
            ['rejects null', null, false],
            ['rejects undefined', undefined, false],
            ['rejects a plain string', 'hi', false],
            ['rejects an array', [{ type: 'text', text: 'hi' }], false],
        ])('%s', (_, input, expected) => {
            expect(isTextContentItem(input)).toBe(expected)
        })
    })

    describe('asString', () => {
        it.each<[name: string, input: unknown, expected: string | undefined]>([
            ['returns a non-empty string unchanged', 'hello', 'hello'],
            ['returns an empty string as itself (caller decides via `||`)', '', ''],
            ['returns undefined for undefined', undefined, undefined],
            ['returns undefined for null', null, undefined],
            ['returns undefined for a number', 42, undefined],
            ['returns undefined for a boolean', true, undefined],
            ['returns undefined for an object', { value: 'oops' }, undefined],
            ['returns undefined for an array', ['oops'], undefined],
        ])('%s', (_, input, expected) => {
            expect(asString(input)).toBe(expected)
        })
    })

    describe('getTraceStepCount', () => {
        const event = (eventName: string): LLMTraceEvent => ({
            id: eventName,
            event: eventName,
            properties: {},
            createdAt: '2026-01-01T00:00:00Z',
        })

        it('counts generations, spans, and embeddings while excluding metric and feedback events', () => {
            expect(
                getTraceStepCount({
                    events: [
                        event('$ai_generation'),
                        event('$ai_span'),
                        event('$ai_embedding'),
                        event('$ai_metric'),
                        event('$ai_feedback'),
                    ],
                })
            ).toBe(3)
        })
    })

    describe('formatAiErrorForDisplay', () => {
        it.each<[string, unknown, string]>([
            ['string passes through', 'rate limit exceeded', 'rate limit exceeded'],
            ['empty string falls back to Unknown error', '', 'Unknown error'],
            ['null falls back to Unknown error', null, 'Unknown error'],
            ['undefined falls back to Unknown error', undefined, 'Unknown error'],
            [
                'plain object is JSON-stringified',
                { message: 'boom', name: 'Error' },
                '{"message":"boom","name":"Error"}',
            ],
            ['array is JSON-stringified', ['a', 'b'], '["a","b"]'],
            ['number is JSON-stringified', 500, '500'],
            ['boolean is JSON-stringified', true, 'true'],
        ])('%s', (_, input, expected) => {
            expect(formatAiErrorForDisplay(input)).toBe(expected)
        })

        it('falls back to String() when JSON.stringify throws (e.g. circular refs)', () => {
            const circular: Record<string, unknown> = {}
            circular.self = circular
            // JSON.stringify throws on circular refs; helper should fall back to String() and not throw.
            expect(() => formatAiErrorForDisplay(circular)).not.toThrow()
            expect(formatAiErrorForDisplay(circular)).toBe('[object Object]')
        })
    })

    // Regressions found by sampling real production payloads across teams. These
    // shapes were mishandled at some point by the recipe pipeline.
    describe('production payload regressions', () => {
        it('null input carries no message', () => {
            // Recipe used to salvage `null` into a spurious empty user message.
            expect(normalizeMessages(null, 'user')).toEqual([])
        })

        it('number/boolean input carries no message', () => {
            expect(normalizeMessages(42, 'user')).toEqual([])
            expect(normalizeMessages(true, 'user')).toEqual([])
        })

        it('a single-field {content} object inherits the default role', () => {
            // Recipe used to force role:user even on the output (assistant) side.
            expect(normalizeMessages({ content: 'hi' }, 'assistant')).toEqual([{ role: 'assistant', content: 'hi' }])
            expect(normalizeMessages({ content: 'hi' }, 'user')).toEqual([{ role: 'user', content: 'hi' }])
        })

        it('an empty top-level tool_calls array adds no synthetic message', () => {
            // Recipe used to append an empty assistant message for `tool_calls: []`.
            // (thinking+text content so the Anthropic envelope path is exercised.)
            const message = {
                role: 'assistant',
                content: [
                    { type: 'thinking', thinking: 'x' },
                    { type: 'text', text: 'done' },
                ],
                tool_calls: [],
            }
            expect(normalizeMessage(message, 'assistant')).toEqual([
                { role: 'assistant (thinking)', content: 'x' },
                { role: 'assistant', content: 'done' },
            ])
        })

        it('OTel parts whose text lives under an unexpected key degrade to empty content, not [null]', () => {
            // `text`-keyed parts (some SDKs) don't match the `content` pluck; the
            // result must collapse to '' rather than a malformed [null] array.
            const message = { role: 'user', parts: [{ type: 'text', text: 'hi' }] }
            expect(normalizeMessage(message, 'user')).toEqual([{ role: 'user', content: '' }])
        })
    })

    // Structured content the recipe pipeline surfaces as canonical messages.
    describe('recipe normalization improvements', () => {
        const expectRecipe = (input: unknown, role: string, expected: unknown): void => {
            expect(normalizeMessages(input, role)).toEqual(expected)
        }

        it('extracts single-field {text}/{message} wrappers instead of stringifying them', () => {
            expectRecipe({ text: 'hello' }, 'assistant', [{ role: 'assistant', content: 'hello' }])
        })

        it('empties null content and drops an empty tool_calls array', () => {
            // content is normalized to '' (renderers expect a string).
            expectRecipe({ role: 'assistant', content: null, tool_calls: [] }, 'assistant', [
                { role: 'assistant', content: '' },
            ])
        })

        it('preserves and canonicalizes a tool_call lacking the type marker', () => {
            // canonicalizes it to {type, id, function:{name, parsed args}}.
            const input = {
                role: 'assistant',
                content: null,
                tool_calls: [
                    {
                        id: 'call_1',
                        caller: { type: 'direct' },
                        index: 0,
                        function: { name: 'send_email', arguments: '{"to":"x@y.com"}' },
                    },
                ],
            }
            expectRecipe(input, 'assistant', [
                {
                    role: 'assistant',
                    content: '',
                    tool_calls: [
                        {
                            type: 'function',
                            id: 'call_1',
                            function: { name: 'send_email', arguments: { to: 'x@y.com' } },
                        },
                    ],
                },
            ])
        })

        it('flattens a doubly-nested message array instead of stringifying it', () => {
            const input = [
                [
                    { role: 'system', content: 'a' },
                    { role: 'user', content: 'b' },
                ],
            ]
            expectRecipe(input, 'user', [
                { role: 'system', content: 'a' },
                { role: 'user', content: 'b' },
            ])
        })

        it('parses typed agent items (tool_call/tool_result) into real tool messages', () => {
            // Flat type-discriminated agent stream (OpenAI Agents SDK and similar).
            const input = [
                { type: 'tool_call', callId: 'c1', name: 'getWeather', arguments: { city: 'NYC' } },
                { type: 'tool_result', callId: 'c1', name: 'getWeather', output: { tempF: 71 } },
            ]
            expectRecipe(input, 'user', [
                {
                    role: 'assistant',
                    content: '',
                    tool_calls: [
                        {
                            type: 'function',
                            id: 'c1',
                            function: { name: 'getWeather', arguments: { city: 'NYC' } },
                        },
                    ],
                },
                { role: 'tool', content: '{"tempF":71}', tool_call_id: 'c1' },
            ])
        })
    })
})
