import { PipelineResultType } from '~/ingestion/framework/results'
import { PluginEvent } from '~/plugin-scaffold'

import { createWarnMissingSessionIdStep } from './warn-missing-session-id-step'

describe('createWarnMissingSessionIdStep', () => {
    const warnMissingSessionIdStep = createWarnMissingSessionIdStep()

    function createTestEvent(properties: Record<string, unknown>): PluginEvent {
        return {
            uuid: 'event-uuid-1',
            event: '$pageview',
            distinct_id: 'user-1',
            team_id: 1,
            properties,
            timestamp: '2024-01-01T00:00:00.000Z',
            now: '2024-01-01T00:00:00.000Z',
            ip: null,
            site_url: '',
        } as PluginEvent
    }

    it.each([
        { description: 'both ids are present', properties: { $window_id: 'window-1', $session_id: 'session-1' } },
        { description: 'neither id is present', properties: {} },
        { description: 'only the session id is present', properties: { $session_id: 'session-1' } },
        { description: 'the window id is empty', properties: { $window_id: '', $session_id: null } },
        { description: 'the window id is not a string', properties: { $window_id: 42, $session_id: null } },
    ])('emits no warning when $description', async ({ properties }) => {
        const result = await warnMissingSessionIdStep({ normalizedEvent: createTestEvent(properties) })

        expect(result.type).toBe(PipelineResultType.OK)
        expect(result.warnings).toHaveLength(0)
    })

    it.each([
        { description: 'null', properties: { $window_id: 'window-1', $session_id: null }, sessionIdType: 'null' },
        { description: 'absent', properties: { $window_id: 'window-1' }, sessionIdType: 'absent' },
        {
            description: 'an empty string',
            properties: { $window_id: 'window-1', $session_id: '   ' },
            sessionIdType: 'empty_string',
        },
        {
            description: 'a number',
            properties: { $window_id: 'window-1', $session_id: 7 },
            sessionIdType: 'number',
        },
    ])(
        'warns when the window id is present and the session id is $description',
        async ({ properties, sessionIdType }) => {
            const result = await warnMissingSessionIdStep({
                normalizedEvent: createTestEvent({ ...properties, $lib: 'web', $lib_version: '1.200.0' }),
            })

            expect(result.type).toBe(PipelineResultType.OK)
            expect(result.warnings).toHaveLength(1)
            expect(result.warnings[0]).toMatchObject({
                type: 'missing_session_id_with_window_id',
                details: {
                    eventUuid: 'event-uuid-1',
                    event: '$pageview',
                    distinctId: 'user-1',
                    sessionIdType,
                    lib: 'web',
                    libVersion: '1.200.0',
                },
            })
        }
    )
})
