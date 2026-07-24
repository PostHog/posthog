import { UUID7, UUIDT } from '~/common/utils/utils'
import { PipelineResultType } from '~/ingestion/framework/results'
import { PluginEvent } from '~/plugin-scaffold'

import { createValidateSessionIdStep } from './validate-session-id-step'

function eventWithSessionId(sessionId: unknown): PluginEvent {
    return {
        distinct_id: 'user-1',
        ip: null,
        site_url: 'http://localhost',
        team_id: 1,
        now: '2020-02-23T02:15:00Z',
        event: 'test event',
        uuid: 'event-uuid',
        properties: sessionId === undefined ? {} : { $session_id: sessionId },
    }
}

describe('validateSessionIdStep', () => {
    const step = createValidateSessionIdStep()

    // No warning: session id is a valid UUID (any version), missing, or null.
    // A false positive here would fire on the majority of well-formed traffic.
    it.each([
        ['a valid UUIDv7', new UUID7().toString()],
        ['a valid UUIDv4-shaped id', new UUIDT().toString()],
        ['an uppercase valid UUID', new UUIDT().toString().toUpperCase()],
        ['no session id', undefined],
        ['a null session id', null],
    ])('does not warn for %s', async (_label, sessionId) => {
        const result = await step({ normalizedEvent: eventWithSessionId(sessionId) })

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.warnings).toEqual([])
        }
    })

    // Warning: session id is present but not a valid UUID, so it silently drops
    // out of session analytics downstream.
    it.each([
        ['a non-UUID string', 'not-a-uuid'],
        ['an empty string', ''],
        ['a numeric session id', 12345],
    ])('warns for %s', async (_label, sessionId) => {
        const result = await step({ normalizedEvent: eventWithSessionId(sessionId) })

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.warnings).toEqual([
                {
                    type: 'invalid_session_id',
                    details: {
                        eventUuid: 'event-uuid',
                        distinctId: 'user-1',
                        sessionId: String(sessionId),
                    },
                },
            ])
        }
    })

    it('truncates an oversized session id in the warning details', async () => {
        const longId = 'x'.repeat(500)
        const result = await step({ normalizedEvent: eventWithSessionId(longId) })

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.warnings[0].details.sessionId).toBe('x'.repeat(200))
        }
    })
})
