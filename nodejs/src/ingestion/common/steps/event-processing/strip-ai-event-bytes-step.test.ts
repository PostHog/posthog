import { ok } from '~/ingestion/framework/results'
import { PluginEvent } from '~/plugin-scaffold'

import { createStripAiEventBytesStep } from './strip-ai-event-bytes-step'

describe('createStripAiEventBytesStep', () => {
    it('drops a client-set $ai_event_bytes and keeps every other property', async () => {
        const normalizedEvent: PluginEvent = {
            distinct_id: 'user',
            ip: null,
            site_url: '',
            team_id: 1,
            now: '2026-01-01T00:00:00Z',
            event: '$ai_generation',
            uuid: '018f0000-0000-7000-8000-000000000000',
            properties: { $ai_event_bytes: 1, $ai_model: 'gpt-4o-mini' },
        }

        const result = await createStripAiEventBytesStep()({ normalizedEvent })

        expect(result).toEqual(
            ok({ normalizedEvent: { ...normalizedEvent, properties: { $ai_model: 'gpt-4o-mini' } } })
        )
    })
})
