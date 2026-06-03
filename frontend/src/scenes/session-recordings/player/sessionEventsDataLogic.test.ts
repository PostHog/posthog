import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import recordingEventsJson from '../__mocks__/recording_events_query'
import { recordingMetaJson } from '../__mocks__/recording_meta'
import { sessionEventsDataLogic } from './sessionEventsDataLogic'
import { sessionRecordingMetaLogic } from './sessionRecordingMetaLogic'

const props = { sessionRecordingId: '2', blobV2PollingDisabled: true }

const FEATURE = 'session-recording-load-full-event-data'

const EVENT_UUID = 'event-uuid-1'
// 'blah' has no core primary property, so it isn't auto-preloaded — only our explicit
// loadFullEventData dispatch triggers the full-properties query, keeping the tests deterministic.
const SESSION_EVENTS_RESPONSE = {
    columns: recordingEventsJson.columns,
    hasMore: false,
    results: [[EVENT_UUID, 'blah', '2023-05-01T14:46:25.000000Z', '', 'window-1', 'https://example.com/x', 'click']],
    types: recordingEventsJson.types,
}

const EMPTY_EVENTS_RESPONSE = {
    columns: recordingEventsJson.columns,
    hasMore: false,
    results: [],
    types: recordingEventsJson.types,
}

type QueryResponder = () => [number, any]

// Route the three HogQL queries the logic issues: the session-events query, the related-events
// query, and the full-event-properties query. `fullEventDataHandler` decides the latter's fate.
function queryMocks(fullEventDataHandler: QueryResponder): Record<string, any> {
    return {
        '/api/environments/:team_id/query/:kind': async (req: any) => {
            const body = await req.json()
            const query = body.query?.query || ''
            if (query.includes('SELECT properties, uuid')) {
                return fullEventDataHandler()
            }
            if (query.includes('$session_id =')) {
                return [200, SESSION_EVENTS_RESPONSE]
            }
            return [200, EMPTY_EVENTS_RESPONSE]
        },
    }
}

describe('sessionEventsDataLogic', () => {
    let logic: ReturnType<typeof sessionEventsDataLogic.build>

    async function mountAndLoadEvents(): Promise<void> {
        logic = sessionEventsDataLogic(props)
        logic.mount()
        const metaLogic = sessionRecordingMetaLogic(props)
        metaLogic.mount()
        metaLogic.actions.loadRecordingMeta()
        await expectLogic(logic).toDispatchActions(['loadEventsSuccess']).toFinishAllListeners()
    }

    describe('loadFullEventData', () => {
        it('flags affected events and captures the actual failure reason when the fetch fails', async () => {
            silenceKeaLoadersErrors()
            const captureSpy = jest.spyOn(posthog, 'captureException').mockImplementation()
            useMocks({
                get: { '/api/environments/:team_id/session_recordings/:id': recordingMetaJson },
                // 4xx is deterministic, so the logic should give up immediately (no retry)
                post: queryMocks(() => [400, { detail: 'invalid query', code: 'bad_request' }]),
            })
            initKeaTests()
            await mountAndLoadEvents()

            const target = logic.values.sessionEventsData!.find((e) => e.id === EVENT_UUID)!
            await expectLogic(logic, () => {
                logic.actions.loadFullEventData(target)
            })
                .toDispatchActions(['loadFullEventDataSuccess'])
                .toFinishAllListeners()

            const updated = logic.values.sessionEventsData!.find((e) => e.id === EVENT_UUID)!
            expect(updated.fullyLoaded).toBe(true)
            expect(updated.propertiesLoadFailed).toBe(true)
            expect(captureSpy).toHaveBeenCalledWith(
                expect.anything(),
                expect.objectContaining({
                    feature: FEATURE,
                    error_kind: 'api',
                    status: 400,
                    code: 'bad_request',
                })
            )
            captureSpy.mockRestore()
            resumeKeaLoadersErrors()
        })

        it('marks events fully and successfully loaded when the fetch succeeds', async () => {
            const captureSpy = jest.spyOn(posthog, 'captureException').mockImplementation()
            useMocks({
                get: { '/api/environments/:team_id/session_recordings/:id': recordingMetaJson },
                post: queryMocks(() => [
                    200,
                    { columns: ['properties', 'uuid'], results: [[JSON.stringify({ $foo: 'bar' }), EVENT_UUID]] },
                ]),
            })
            initKeaTests()
            await mountAndLoadEvents()

            const event = logic.values.sessionEventsData!.find((e) => e.id === EVENT_UUID)!
            await expectLogic(logic, () => {
                logic.actions.loadFullEventData(event)
            })
                .toDispatchActions(['loadFullEventDataSuccess'])
                .toFinishAllListeners()

            const updated = logic.values.sessionEventsData!.find((e) => e.id === EVENT_UUID)!
            expect(updated.fullyLoaded).toBe(true)
            expect(updated.propertiesLoadFailed).toBe(false)
            expect(updated.properties).toMatchObject({ $foo: 'bar' })
            expect(captureSpy).not.toHaveBeenCalledWith(
                expect.anything(),
                expect.objectContaining({ feature: FEATURE })
            )
            captureSpy.mockRestore()
        })

        it('retries transient server errors before flagging the events', async () => {
            silenceKeaLoadersErrors()
            const captureSpy = jest.spyOn(posthog, 'captureException').mockImplementation()
            let fullDataAttempts = 0
            useMocks({
                get: { '/api/environments/:team_id/session_recordings/:id': recordingMetaJson },
                post: queryMocks(() => {
                    fullDataAttempts += 1
                    // fail twice with a retriable 5xx, then succeed
                    if (fullDataAttempts < 3) {
                        return [500, { detail: 'temporary' }]
                    }
                    return [
                        200,
                        { columns: ['properties', 'uuid'], results: [[JSON.stringify({ $foo: 'bar' }), EVENT_UUID]] },
                    ]
                }),
            })
            initKeaTests()
            await mountAndLoadEvents()

            const event = logic.values.sessionEventsData!.find((e) => e.id === EVENT_UUID)!
            await expectLogic(logic, () => {
                logic.actions.loadFullEventData(event)
            })
                .toDispatchActions(['loadFullEventDataSuccess'])
                .toFinishAllListeners()

            expect(fullDataAttempts).toBe(3)
            const updated = logic.values.sessionEventsData!.find((e) => e.id === EVENT_UUID)!
            expect(updated.fullyLoaded).toBe(true)
            expect(updated.propertiesLoadFailed).toBe(false)
            expect(captureSpy).not.toHaveBeenCalledWith(
                expect.anything(),
                expect.objectContaining({ feature: FEATURE })
            )
            captureSpy.mockRestore()
            resumeKeaLoadersErrors()
        })
    })
})
