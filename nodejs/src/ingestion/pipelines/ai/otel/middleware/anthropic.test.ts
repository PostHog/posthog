import { convertOtelEvent } from '~/ingestion/pipelines/ai/otel/index'
import { createEvent } from '~/ingestion/pipelines/ai/otel/test-helpers'

import { anthropic } from './anthropic'

const convert = (eventName: string, properties: Record<string, unknown>): Record<string, unknown> => {
    const event = createEvent(eventName, properties)
    convertOtelEvent(event)
    return event.properties!
}

describe('anthropic middleware', () => {
    it.each([
        ['a request span', { 'anthropic.request.id': 'req_example' }],
        ['a session span', { 'anthropic.session.id': 'sesn_example' }],
        ['a tool span', { 'anthropic.tool_result.content': '[]' }],
    ])('matches %s', (_label, properties) => {
        expect(anthropic.matches(createEvent('$ai_span', properties))).toBe(true)
    })

    it.each([
        ['no vendor attribute', { 'gen_ai.provider.name': 'anthropic', 'gen_ai.request.model': 'claude-example' }],
        ['no properties at all', {}],
    ])('does not match a span with %s', (_label, properties) => {
        expect(anthropic.matches(createEvent('$ai_generation', properties))).toBe(false)
    })

    it('leaves a traceloop span to the traceloop middleware', () => {
        const props = convert('$ai_span', { 'llm.request.type': 'chat', 'anthropic.request.id': 'req_example' })
        expect(props['$ai_lib']).toBe('opentelemetry/traceloop')
    })

    it('marks input tokens as cache-inclusive and maps the cache write breakdown', () => {
        const props = convert('$ai_generation', {
            'anthropic.request.id': 'req_example',
            'gen_ai.usage.input_tokens': 1000,
            'gen_ai.usage.cache_read.input_tokens': 600,
            'gen_ai.usage.cache_write.input_tokens': 300,
            'anthropic.usage.cache_creation.ephemeral_5m_input_tokens': 200,
            'anthropic.usage.cache_creation.ephemeral_1h_input_tokens': 100,
        })
        expect(props).toMatchObject({
            $ai_lib: 'opentelemetry/anthropic',
            $ai_input_tokens: 1000,
            $ai_cache_read_input_tokens: 600,
            $ai_cache_creation_input_tokens: 300,
            $ai_cache_creation_5m_input_tokens: 200,
            $ai_cache_creation_1h_input_tokens: 100,
            $ai_cache_reporting_exclusive: false,
        })
        expect(props['anthropic.usage.cache_creation.ephemeral_5m_input_tokens']).toBeUndefined()
        expect(props['anthropic.usage.cache_creation.ephemeral_1h_input_tokens']).toBeUndefined()
    })

    it.each([
        ['a numeric total', 300],
        ['a total sent as a numeric string', '300'],
    ])('does not use a cache write breakdown that does not add up to %s', (_label, total) => {
        const props = convert('$ai_generation', {
            'anthropic.request.id': 'req_example',
            'gen_ai.usage.input_tokens': 1000,
            'gen_ai.usage.cache_write.input_tokens': total,
            'anthropic.usage.cache_creation.ephemeral_5m_input_tokens': 200,
            'anthropic.usage.cache_creation.ephemeral_1h_input_tokens': 0,
        })
        expect(props['$ai_cache_creation_input_tokens']).toBe(total)
        expect(props['$ai_cache_creation_5m_input_tokens']).toBeUndefined()
        expect(props['$ai_cache_creation_1h_input_tokens']).toBeUndefined()
        expect(props['anthropic.usage.cache_creation.ephemeral_5m_input_tokens']).toBe(200)
    })

    it('keeps an explicit cache write breakdown', () => {
        const props = convert('$ai_generation', {
            'anthropic.request.id': 'req_example',
            'gen_ai.usage.input_tokens': 1000,
            $ai_cache_creation_5m_input_tokens: 50,
            $ai_cache_creation_1h_input_tokens: 0,
            'anthropic.usage.cache_creation.ephemeral_5m_input_tokens': 200,
            'anthropic.usage.cache_creation.ephemeral_1h_input_tokens': 0,
        })
        expect(props).toMatchObject({ $ai_cache_creation_5m_input_tokens: 50, $ai_cache_creation_1h_input_tokens: 0 })
        expect(props['$ai_cache_creation_input_tokens']).toBeUndefined()
    })

    it('counts a missing TTL as zero when a span reports one cache write TTL without a total', () => {
        const props = convert('$ai_generation', {
            'anthropic.request.id': 'req_example',
            'gen_ai.usage.input_tokens': 1000,
            'anthropic.usage.cache_creation.ephemeral_1h_input_tokens': 250,
        })
        expect(props).toMatchObject({
            $ai_cache_creation_input_tokens: 250,
            $ai_cache_creation_5m_input_tokens: 0,
            $ai_cache_creation_1h_input_tokens: 250,
        })
    })

    it.each([
        ['gen_ai.usage.reasoning.output_tokens', '$ai_reasoning_tokens', 120],
        ['gen_ai.request.max_tokens', '$ai_max_tokens', 4096],
        ['gen_ai.request.stream', '$ai_stream', true],
    ])('renames %s to %s for these spans only', (otelKey, phKey, value) => {
        const matched = convert('$ai_generation', { 'anthropic.request.id': 'req_example', [otelKey]: value })
        expect(matched[phKey]).toBe(value)
        expect(matched[otelKey]).toBeUndefined()

        const otherProducer = convert('$ai_generation', { 'gen_ai.provider.name': 'example', [otelKey]: value })
        expect(otherProducer[phKey]).toBeUndefined()
        expect(otherProducer[otelKey]).toBe(value)
    })

    it('keeps the cache write total from the older attribute name when a span reports both names', () => {
        const props = convert('$ai_generation', {
            'anthropic.request.id': 'req_example',
            'gen_ai.usage.cache_creation.input_tokens': 300,
            'gen_ai.usage.cache_write.input_tokens': 999,
        })
        expect(props['$ai_cache_creation_input_tokens']).toBe(300)
        expect(props['gen_ai.usage.cache_write.input_tokens']).toBeUndefined()
    })

    it('adds compaction tokens to the generation, which reports them outside its own usage', () => {
        const props = convert('$ai_generation', {
            'anthropic.request.id': 'req_example',
            'gen_ai.usage.input_tokens': 600,
            'gen_ai.usage.output_tokens': 200,
            'anthropic.usage.compaction.input_tokens': 5000,
            'anthropic.usage.compaction.output_tokens': 700,
        })
        expect(props).toMatchObject({
            $ai_input_tokens: 5600,
            $ai_output_tokens: 900,
            'anthropic.usage.compaction.input_tokens': 5000,
            'anthropic.usage.compaction.output_tokens': 700,
        })
    })

    it('does not set the cache reporting mode on a span without token usage', () => {
        const props = convert('$ai_span', { 'anthropic.request.id': 'req_example' })
        expect(props['$ai_cache_reporting_exclusive']).toBeUndefined()
    })

    it('keeps an explicit cache reporting mode', () => {
        const props = convert('$ai_generation', {
            'anthropic.request.id': 'req_example',
            'gen_ai.usage.input_tokens': 10,
            $ai_cache_reporting_exclusive: true,
        })
        expect(props['$ai_cache_reporting_exclusive']).toBe(true)
    })

    it.each([['anthropic.message.stop_reason'], ['anthropic.session.turn.stop_reason']])(
        'maps %s to $ai_stop_reason',
        (key) => {
            const props = convert('$ai_generation', { [key]: 'end_turn' })
            expect(props['$ai_stop_reason']).toBe('end_turn')
            expect(props[key]).toBeUndefined()
        }
    )

    it.each([
        [
            'the session id over the conversation id',
            { 'anthropic.session.id': 'sesn_example', 'gen_ai.conversation.id': 'thread_example' },
            'sesn_example',
        ],
        [
            'the conversation id when there is no session id',
            { 'gen_ai.conversation.id': 'thread_example' },
            'thread_example',
        ],
        [
            'an explicit $ai_session_id over both',
            {
                $ai_session_id: 'explicit',
                'anthropic.session.id': 'sesn_example',
                'gen_ai.conversation.id': 'thread_example',
            },
            'explicit',
        ],
    ])('uses %s as $ai_session_id', (_label, properties, expected) => {
        const props = convert('$ai_span', { 'anthropic.request.id': 'req_example', ...properties })
        expect(props['$ai_session_id']).toBe(expected)
    })

    it('turns a tool execution span into a named span with input and output state', () => {
        const props = convert('$ai_span', {
            $ai_parent_id: 'parent-span',
            $otel_span_name: 'anthropic.tool_use lookup_part',
            'gen_ai.operation.name': 'execute_tool',
            'gen_ai.tool.name': 'lookup_part',
            'gen_ai.tool.call.id': 'call_example',
            'gen_ai.tool.call.arguments': '{"part_number":"P-100"}',
            'anthropic.tool_result.content': '[{"type":"text","text":"7 in stock"}]',
        })
        expect(props).toMatchObject({
            $ai_span_name: 'lookup_part',
            $ai_input_state: { part_number: 'P-100' },
            $ai_output_state: [{ type: 'text', text: '7 in stock' }],
            'gen_ai.tool.call.id': 'call_example',
        })
        expect(props['gen_ai.tool.call.arguments']).toBeUndefined()
        expect(props['anthropic.tool_result.content']).toBeUndefined()
    })

    it('keeps a tool result that is not JSON as a string', () => {
        const props = convert('$ai_span', {
            $ai_parent_id: 'parent-span',
            'gen_ai.operation.name': 'execute_tool',
            'gen_ai.tool.name': 'lookup_part',
            'anthropic.tool_result.content': 'plain text result',
        })
        expect(props['$ai_output_state']).toBe('plain text result')
    })

    it.each([
        [
            'counts server-side web searches and ignores other tool calls',
            [
                { type: 'tool_call', id: 'srvtoolu_example1', name: 'web_search', arguments: { query: 'a' } },
                { type: 'server_tool_call', id: 'srvtoolu_example2', name: 'web_search', arguments: { query: 'b' } },
                { type: 'tool_call', id: 'srvtoolu_example3', name: 'code_execution', arguments: {} },
                { type: 'text', content: 'done' },
            ],
            2,
        ],
        [
            'ignores a client tool that is also named web_search',
            [{ type: 'tool_call', id: 'toolu_example', name: 'web_search', arguments: { query: 'a' } }],
            undefined,
        ],
        ['sets no count when there were no searches', [{ type: 'text', content: 'done' }], undefined],
    ])('%s', (_label, parts, expected) => {
        const props = convert('$ai_generation', {
            'anthropic.request.id': 'req_example',
            'gen_ai.output.messages': JSON.stringify([{ role: 'assistant', parts }]),
        })
        expect(props['$ai_web_search_count']).toBe(expected)
    })

    it('keeps an explicit web search count', () => {
        const props = convert('$ai_generation', {
            'anthropic.request.id': 'req_example',
            $ai_web_search_count: 5,
            'gen_ai.output.messages': JSON.stringify([
                { role: 'assistant', parts: [{ type: 'tool_call', id: 'srvtoolu_example', name: 'web_search' }] },
            ]),
        })
        expect(props['$ai_web_search_count']).toBe(5)
    })
})
