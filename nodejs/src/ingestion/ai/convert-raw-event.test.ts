import { PluginEvent } from '@posthog/plugin-scaffold'

import { convertRawEvent } from './convert-raw-event'

const createEvent = (properties?: Record<string, unknown>): PluginEvent => ({
    event: '$ai_generation',
    distinct_id: 'user-123',
    team_id: 1,
    properties,
    uuid: 'test-uuid',
    timestamp: new Date().toISOString(),
    ip: '127.0.0.1',
    site_url: 'https://app.posthog.com',
    now: new Date().toISOString(),
})

describe('convertRawEvent', () => {
    it('maps OTel attributes to PostHog properties when source is otel', () => {
        const event = createEvent({
            $ai_ingestion_source: 'otel',
            'gen_ai.request.model': 'gpt-4',
            'gen_ai.provider.name': 'openai',
        })

        convertRawEvent(event)

        expect(event.properties!.$ai_model).toBe('gpt-4')
        expect(event.properties!.$ai_provider).toBe('openai')
        expect(event.properties!['gen_ai.request.model']).toBeUndefined()
        expect(event.properties!['gen_ai.provider.name']).toBeUndefined()
    })

    it.each([
        ['undefined source', {}],
        ['sdk source', { $ai_ingestion_source: 'sdk' }],
        ['missing properties', undefined],
    ])('is a no-op when %s', (_label, properties) => {
        const event = createEvent(properties)
        const before = event.properties ? { ...event.properties } : undefined
        convertRawEvent(event)
        expect(event.properties).toEqual(before)
    })

    describe('debug mode', () => {
        it('sets $ai_debug flag and snapshots raw properties into $ai_debug_data', () => {
            const event = createEvent({
                $ai_ingestion_source: 'otel',
                'posthog.ai.debug': 'true',
                'gen_ai.request.model': 'gpt-4',
                'gen_ai.provider.name': 'openai',
            })

            convertRawEvent(event)

            expect(event.properties!.$ai_model).toBe('gpt-4')
            expect(event.properties!['gen_ai.request.model']).toBeUndefined()

            expect(event.properties!.$ai_debug).toBe(true)
            expect(event.properties!.$ai_debug_data).toBeDefined()
            expect(event.properties!.$ai_debug_data['gen_ai.request.model']).toBe('gpt-4')
            expect(event.properties!.$ai_debug_data['gen_ai.provider.name']).toBe('openai')
        })

        it.each([
            ['absent', { $ai_ingestion_source: 'otel', 'gen_ai.request.model': 'gpt-4' }],
            ['empty string', { $ai_ingestion_source: 'otel', 'posthog.ai.debug': '', 'gen_ai.request.model': 'gpt-4' }],
            ['zero', { $ai_ingestion_source: 'otel', 'posthog.ai.debug': 0, 'gen_ai.request.model': 'gpt-4' }],
            ['false', { $ai_ingestion_source: 'otel', 'posthog.ai.debug': false, 'gen_ai.request.model': 'gpt-4' }],
        ])('does not set debug properties when posthog.ai.debug is %s', (_label, properties) => {
            const event = createEvent(properties)
            convertRawEvent(event)
            expect(event.properties!.$ai_debug).toBeUndefined()
            expect(event.properties!.$ai_debug_data).toBeUndefined()
        })
    })
})
