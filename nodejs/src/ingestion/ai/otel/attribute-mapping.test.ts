import { PluginEvent } from '@posthog/plugin-scaffold'

import { mapOtelAttributes } from './attribute-mapping'

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

describe('mapOtelAttributes', () => {
    it.each([
        ['gen_ai.input.messages', '$ai_input'],
        ['gen_ai.output.messages', '$ai_output_choices'],
        ['gen_ai.usage.input_tokens', '$ai_input_tokens'],
        ['gen_ai.usage.output_tokens', '$ai_output_tokens'],
        ['gen_ai.request.model', '$ai_model'],
        ['gen_ai.provider.name', '$ai_provider'],
        ['server.address', '$ai_base_url'],
        ['telemetry.sdk.name', '$ai_lib'],
        ['telemetry.sdk.version', '$ai_lib_version'],
        ['$otel_span_name', '$ai_span_name'],
    ])('renames %s to %s', (otelKey, phKey) => {
        const event = createEvent('$ai_generation', { [otelKey]: 'test-value' })
        mapOtelAttributes(event)
        expect(event.properties![phKey]).toBe('test-value')
        expect(event.properties![otelKey]).toBeUndefined()
    })

    it('JSON-parses string values for $ai_input and $ai_output_choices', () => {
        const event = createEvent('$ai_generation', {
            'gen_ai.input.messages': '[{"role": "user", "content": "Hello"}]',
            'gen_ai.output.messages': '[{"role": "assistant", "content": "Hi"}]',
        })
        mapOtelAttributes(event)
        expect(event.properties!.$ai_input).toEqual([{ role: 'user', content: 'Hello' }])
        expect(event.properties!.$ai_output_choices).toEqual([{ role: 'assistant', content: 'Hi' }])
    })

    it('keeps original string when JSON parsing fails', () => {
        const event = createEvent('$ai_generation', {
            'gen_ai.input.messages': 'not valid json',
        })
        mapOtelAttributes(event)
        expect(event.properties!.$ai_input).toBe('not valid json')
    })

    it('does not JSON-parse already-parsed objects', () => {
        const parsed = [{ role: 'user', content: 'Hello' }]
        const event = createEvent('$ai_generation', {
            'gen_ai.input.messages': parsed,
        })
        mapOtelAttributes(event)
        expect(event.properties!.$ai_input).toEqual(parsed)
    })

    it('preserves unknown attributes', () => {
        const event = createEvent('$ai_generation', {
            'custom.attribute': 'custom-value',
            'gen_ai.request.model': 'gpt-4',
        })
        mapOtelAttributes(event)
        expect(event.properties!['custom.attribute']).toBe('custom-value')
        expect(event.properties!.$ai_model).toBe('gpt-4')
    })

    it.each([
        ['gen_ai.system', '$ai_provider', 'openai'],
        ['gen_ai.response.model', '$ai_model', 'gpt-4-turbo'],
    ])('uses %s as fallback for %s', (otelKey, phKey, value) => {
        const event = createEvent('$ai_generation', { [otelKey]: value })
        mapOtelAttributes(event)
        expect(event.properties![phKey]).toBe(value)
        expect(event.properties![otelKey]).toBeUndefined()
    })

    it.each([
        ['gen_ai.system', '$ai_provider', 'gen_ai.provider.name'],
        ['gen_ai.response.model', '$ai_model', 'gen_ai.request.model'],
    ])('does not override %s when primary mapping for %s exists', (fallbackKey, phKey, primaryKey) => {
        const event = createEvent('$ai_generation', { [primaryKey]: 'primary', [fallbackKey]: 'fallback' })
        mapOtelAttributes(event)
        expect(event.properties![phKey]).toBe('primary')
        expect(event.properties![fallbackKey]).toBeUndefined()
    })

    it.each(['telemetry.sdk.language', 'gen_ai.operation.name', 'posthog.ai.debug'])(
        'strips %s from properties',
        (key) => {
            const event = createEvent('$ai_generation', { [key]: 'some-value' })
            mapOtelAttributes(event)
            expect(event.properties![key]).toBeUndefined()
        }
    )

    it('computes $ai_latency from OTel timestamps', () => {
        const event = createEvent('$ai_generation', {
            $otel_start_time_unix_nano: '1704067200000000000',
            $otel_end_time_unix_nano: '1704067201500000000',
        })
        mapOtelAttributes(event)
        expect(event.properties!['$ai_latency']).toBe(1.5)
        expect(event.properties!['$otel_start_time_unix_nano']).toBeUndefined()
        expect(event.properties!['$otel_end_time_unix_nano']).toBeUndefined()
    })

    it('does not set $ai_latency when end <= start', () => {
        const event = createEvent('$ai_generation', {
            $otel_start_time_unix_nano: '1000000000000000000',
            $otel_end_time_unix_nano: '0',
        })
        mapOtelAttributes(event)
        expect(event.properties!['$ai_latency']).toBeUndefined()
    })

    it('strips OTel timestamp properties even when latency cannot be computed', () => {
        const event = createEvent('$ai_generation', {
            $otel_start_time_unix_nano: '1000000000000000000',
            $otel_end_time_unix_nano: '0',
        })
        mapOtelAttributes(event)
        expect(event.properties!['$otel_start_time_unix_nano']).toBeUndefined()
        expect(event.properties!['$otel_end_time_unix_nano']).toBeUndefined()
    })

    it('promotes root $ai_span to $ai_trace', () => {
        const event = createEvent('$ai_span', {
            $otel_start_time_unix_nano: '0',
            $otel_end_time_unix_nano: '0',
        })
        mapOtelAttributes(event)
        expect(event.event).toBe('$ai_trace')
    })

    it('does not promote $ai_span with parent to $ai_trace', () => {
        const event = createEvent('$ai_span', {
            $ai_parent_id: 'abc123',
            $otel_start_time_unix_nano: '0',
            $otel_end_time_unix_nano: '0',
        })
        mapOtelAttributes(event)
        expect(event.event).toBe('$ai_span')
    })

    it('does not promote $ai_generation to $ai_trace', () => {
        const event = createEvent('$ai_generation', {
            $otel_start_time_unix_nano: '0',
            $otel_end_time_unix_nano: '0',
        })
        mapOtelAttributes(event)
        expect(event.event).toBe('$ai_generation')
    })
})
