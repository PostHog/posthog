import { PluginEvent } from '~/plugin-scaffold'

import { MAX_TOOL_INTENT_LENGTH } from './extract-tool-usage'
import { processAiToolUsageExtraction } from './index'

const generation = (properties: Record<string, unknown>): PluginEvent =>
    ({ event: '$ai_generation', properties, distinct_id: 'user', team_id: 1, uuid: 'event' }) as unknown as PluginEvent

const resultProperties = (properties: Record<string, unknown>): Record<string, unknown> => {
    const out = processAiToolUsageExtraction(generation(properties)).properties!
    return {
        count: out['$ai_tool_result_count'],
        errorCount: out['$ai_tool_error_count'],
        results: out['$ai_tool_results'],
        errors: out['$ai_tool_errors'],
    }
}

describe('processAiToolUsageExtraction', () => {
    describe('tool results in $ai_input', () => {
        it.each([
            [
                'Anthropic tool_result with is_error, named from the earlier tool_use',
                [
                    { role: 'user', content: 'Refund order 42' },
                    {
                        role: 'assistant',
                        content: [
                            { type: 'tool_use', id: 'toolu_1', name: 'lookup_order', input: {} },
                            { type: 'tool_use', id: 'toolu_2', name: 'issue_refund', input: {} },
                        ],
                    },
                    {
                        role: 'user',
                        content: [
                            { type: 'tool_result', tool_use_id: 'toolu_1', content: 'order found' },
                            { type: 'tool_result', tool_use_id: 'toolu_2', content: 'card declined', is_error: true },
                        ],
                    },
                ],
                { count: 2, errorCount: 1, results: 'lookup_order,issue_refund', errors: 'issue_refund' },
            ],
            [
                'OpenAI chat tool messages, error read from the result text',
                [
                    { role: 'user', content: 'Weather in Paris and Rome?' },
                    {
                        role: 'assistant',
                        content: null,
                        tool_calls: [
                            { id: 'call_a', type: 'function', function: { name: 'get_weather', arguments: '{}' } },
                            { id: 'call_b', type: 'function', function: { name: 'get_weather', arguments: '{}' } },
                        ],
                    },
                    { role: 'tool', tool_call_id: 'call_a', content: '18C and sunny' },
                    { role: 'tool', tool_call_id: 'call_b', content: 'Error: upstream timed out' },
                ],
                { count: 2, errorCount: 1, results: 'get_weather,get_weather', errors: 'get_weather' },
            ],
            [
                'Vercel AI SDK tool-result with an error output type',
                [
                    {
                        role: 'assistant',
                        content: [{ type: 'tool-call', toolCallId: 'c1', toolName: 'search_docs', input: {} }],
                    },
                    {
                        role: 'tool',
                        content: [
                            {
                                type: 'tool-result',
                                toolCallId: 'c1',
                                toolName: 'search_docs',
                                output: { type: 'error-text', value: 'index unavailable' },
                            },
                        ],
                    },
                ],
                { count: 1, errorCount: 1, results: 'search_docs', errors: 'search_docs' },
            ],
            [
                'OTel gen_ai tool_call_response parts',
                [
                    {
                        role: 'assistant',
                        parts: [{ type: 'tool_call', id: 't1', name: 'read_file', arguments: {} }],
                    },
                    { role: 'tool', parts: [{ type: 'tool_call_response', id: 't1', output: 'file contents' }] },
                ],
                { count: 1, errorCount: 0, results: 'read_file', errors: undefined },
            ],
            [
                'OpenAI Responses function_call_output items',
                [
                    { role: 'user', content: 'Find the invoice' },
                    { type: 'function_call', call_id: 'fc_1', name: 'find_invoice', arguments: '{}' },
                    { type: 'function_call_output', call_id: 'fc_1', output: 'invoice INV-7' },
                ],
                { count: 1, errorCount: 0, results: 'find_invoice', errors: undefined },
            ],
            [
                'only the trailing results, so earlier turns are not counted again',
                [
                    { role: 'assistant', content: [{ type: 'tool_use', id: 'old', name: 'list_files', input: {} }] },
                    { role: 'user', content: [{ type: 'tool_result', tool_use_id: 'old', is_error: true }] },
                    { role: 'assistant', content: [{ type: 'tool_use', id: 'new', name: 'read_file', input: {} }] },
                    { role: 'user', content: [{ type: 'tool_result', tool_use_id: 'new', content: 'ok' }] },
                ],
                { count: 1, errorCount: 0, results: 'read_file', errors: undefined },
            ],
            [
                'a result with no id or name is counted but not named',
                [
                    { role: 'assistant', content: 'checking', tool_calls: [] },
                    { role: 'tool', content: 'Error: permission denied' },
                ],
                { count: 1, errorCount: 1, results: undefined, errors: undefined },
            ],
        ])('%s', (_, input, expected) => {
            expect(resultProperties({ $ai_input: input })).toEqual(expected)
        })

        it.each([
            ['the input ends with a user message', [{ role: 'user', content: 'hello' }]],
            ['the input is missing', undefined],
            ['the input is not JSON', 'just a prompt mentioning "tool"'],
        ])('sets nothing when %s', (_, input) => {
            expect(resultProperties({ $ai_input: input })).toEqual({
                count: undefined,
                errorCount: undefined,
                results: undefined,
                errors: undefined,
            })
        })

        it('reads a JSON-stringified input', () => {
            const input = JSON.stringify([
                { role: 'assistant', content: [{ type: 'tool_use', id: 'x', name: 'calc', input: {} }] },
                { role: 'user', content: [{ type: 'tool_result', tool_use_id: 'x', is_error: true }] },
            ])
            expect(resultProperties({ $ai_input: input })).toEqual({
                count: 1,
                errorCount: 1,
                results: 'calc',
                errors: 'calc',
            })
        })

        it('keeps a result count the client sent', () => {
            const out = processAiToolUsageExtraction(
                generation({
                    $ai_tool_result_count: 5,
                    $ai_input: [{ role: 'tool', tool_call_id: 'a', name: 'calc', content: 'Error: x' }],
                })
            ).properties!
            expect(out['$ai_tool_result_count']).toBe(5)
            expect(out['$ai_tool_errors']).toBeUndefined()
        })
    })

    describe('unknown tools', () => {
        it.each([
            [
                'OpenAI function definitions',
                [{ type: 'function', function: { name: 'get_weather' } }],
                'get_weather,send_email',
                'send_email',
            ],
            ['Anthropic definitions', [{ name: 'calc', input_schema: {} }], 'calc', undefined],
            ['a JSON-stringified list of names', JSON.stringify(['search', 'fetch']), 'search,browse,browse', 'browse'],
            ['Vercel AI SDK tool record', { search: { description: 's' } }, 'search,delete_file', 'delete_file'],
            [
                'Gemini function declarations',
                [{ functionDeclarations: [{ name: 'search_tags' }] }],
                'search_tags,create_tag',
                'create_tag',
            ],
            [
                'a provider built-in tool without a name, so nothing is flagged',
                [{ type: 'function', function: { name: 'calc' } }, { type: 'web_search_preview' }],
                'calc,web_search',
                undefined,
            ],
        ])('%s', (_, tools, called, expected) => {
            const out = processAiToolUsageExtraction(
                generation({ $ai_tools: tools, $ai_tools_called: called })
            ).properties!
            expect(out['$ai_tools_unknown']).toEqual(expected)
        })
    })

    describe('intent', () => {
        it.each([
            [
                'Anthropic text before a tool_use, without the thinking',
                [
                    {
                        role: 'assistant',
                        content: [
                            { type: 'thinking', thinking: 'private reasoning' },
                            { type: 'text', text: 'Let me look up\nthat invoice.' },
                            { type: 'tool_use', id: 't', name: 'find_invoice', input: {} },
                        ],
                    },
                ],
                'Let me look up that invoice.',
            ],
            [
                'OpenAI message content next to tool_calls',
                [{ message: { role: 'assistant', content: 'Checking the weather.', tool_calls: [] } }],
                'Checking the weather.',
            ],
            [
                'OpenAI Responses output_text',
                [{ type: 'message', role: 'assistant', content: [{ type: 'output_text', text: 'Searching now.' }] }],
                'Searching now.',
            ],
            ['structured JSON output', [{ role: 'assistant', content: '{"answer": 4}' }], undefined],
        ])('%s', (_, outputChoices, expected) => {
            const out = processAiToolUsageExtraction(
                generation({ $ai_output_choices: outputChoices, $ai_tools_called: 'find_invoice' })
            ).properties!
            expect(out['$ai_tool_intent']).toEqual(expected)
        })

        it('is only set when the generation called tools', () => {
            const out = processAiToolUsageExtraction(
                generation({ $ai_output_choices: [{ role: 'assistant', content: 'Hello there' }] })
            ).properties!
            expect(out['$ai_tool_intent']).toBeUndefined()
        })

        it('is truncated', () => {
            const out = processAiToolUsageExtraction(
                generation({
                    $ai_output_choices: [{ role: 'assistant', content: 'a'.repeat(MAX_TOOL_INTENT_LENGTH * 2) }],
                    $ai_tools_called: 'calc',
                })
            ).properties!
            expect(out['$ai_tool_intent']).toHaveLength(MAX_TOOL_INTENT_LENGTH)
        })
    })

    it('ignores events that are not generations', () => {
        const event = {
            event: '$ai_span',
            properties: { $ai_input: [{ role: 'tool', tool_call_id: 'a', name: 'calc', content: 'Error: x' }] },
        } as unknown as PluginEvent
        expect(processAiToolUsageExtraction(event).properties!['$ai_tool_result_count']).toBeUndefined()
    })
})
