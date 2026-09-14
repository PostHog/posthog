import { UUID7, UUIDT } from '~/common/utils/utils'
import { PipelineResultType } from '~/ingestion/framework/results'
import { PluginEvent } from '~/plugin-scaffold'

import { ValidateSessionIdStepInput, createValidateSessionIdStep } from './validate-session-id-step'

function eventWith(sessionId: unknown): ValidateSessionIdStepInput {
    const properties = sessionId === undefined ? {} : { $session_id: sessionId }
    return {
        normalizedEvent: {
            uuid: 'event-uuid',
            event: '$pageview',
            distinct_id: 'user-1',
            properties,
        } as unknown as PluginEvent,
    }
}

describe('validateSessionIdStep', () => {
    const step = createValidateSessionIdStep()

    // No warning: a valid UUID (any version, any case), or no session id at all.
    it.each([
        ['a valid UUIDv7', new UUID7().toString()],
        ['a valid UUID', new UUIDT().toString()],
        ['an uppercase valid UUID', new UUIDT().toString().toUpperCase()],
        ['a missing session id', undefined],
        ['a null session id', null],
    ])('does not warn for %s', async (_label, sessionId) => {
        const result = await step(eventWith(sessionId))
        expect(result.type).toBe(PipelineResultType.OK)
        expect(result.warnings).toEqual([])
    })

    // Warning: present but not a valid UUID, so it silently drops from session analytics.
    it.each([
        ['a non-UUID string', 'not-a-uuid'],
        ['an empty string', ''],
        ['a numeric id', 12345],
    ])('warns for %s', async (_label, sessionId) => {
        const result = await step(eventWith(sessionId))
        expect(result.warnings).toEqual([
            {
                type: 'invalid_event_session_id',
                details: { eventUuid: 'event-uuid', sessionId: String(sessionId) },
            },
        ])
    })

    it('truncates an oversized session id in the warning details', async () => {
        const result = await step(eventWith('x'.repeat(500)))
        expect(result.warnings[0].details.sessionId).toBe('x'.repeat(200))
    })
})
