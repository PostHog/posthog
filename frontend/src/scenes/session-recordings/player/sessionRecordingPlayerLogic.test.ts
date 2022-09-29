import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { initKeaTests } from '~/test/init'
import { expectLogic } from 'kea-test-utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { sessionRecordingDataLogic } from 'scenes/session-recordings/player/sessionRecordingDataLogic'
import { sharedListLogic } from 'scenes/session-recordings/player/list/sharedListLogic'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import { useMocks } from '~/mocks/jest'
import recordingSnapshotsJson from 'scenes/session-recordings/__mocks__/recording_snapshots.json'
import recordingMetaJson from 'scenes/session-recordings/__mocks__/recording_meta.json'
import recordingEventsJson from 'scenes/session-recordings/__mocks__/recording_events.json'

describe('sessionRecordingPlayerLogic', () => {
    let logic: ReturnType<typeof sessionRecordingPlayerLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/session_recordings/:id/snapshots': { result: recordingSnapshotsJson },
                '/api/projects/:team/session_recordings/:id': { result: recordingMetaJson },
                '/api/projects/:team/events': { results: recordingEventsJson },
            },
        })
        initKeaTests()
        logic = sessionRecordingPlayerLogic({ sessionRecordingId: '2', playerKey: 'test' })
        logic.mount()
    })

    describe('core assumptions', () => {
        it('mounts other logics', async () => {
            await expectLogic(logic).toMount([
                eventUsageLogic,
                sessionRecordingDataLogic({ sessionRecordingId: '2' }),
                sharedListLogic({ sessionRecordingId: '2', playerKey: 'test' }),
                playerSettingsLogic,
            ])
        })
    })

    describe('matching', () => {
        const listOfMatchingEvents = [
            { uuid: '1', timestamp: '2022-06-01T12:00:00.000Z', session_id: '1', window_id: '1' },
            { uuid: '2', timestamp: '2022-06-01T12:01:00.000Z', session_id: '1', window_id: '1' },
            { uuid: '3', timestamp: '2022-06-01T12:02:00.000Z', session_id: '1', window_id: '1' },
        ]
        it('starts as empty list', async () => {
            await expectLogic(logic).toMatchValues({
                matching: [],
            })
        })
        it('initialized through props', async () => {
            logic = sessionRecordingPlayerLogic({
                sessionRecordingId: '3',
                playerKey: 'test',
                matching: [
                    {
                        events: listOfMatchingEvents,
                    },
                ],
            })
            logic.mount()
            await expectLogic(logic).toMatchValues({
                matching: [
                    {
                        events: listOfMatchingEvents,
                    },
                ],
            })
        })
        it('changes when filter results change', async () => {
            logic = sessionRecordingPlayerLogic({
                sessionRecordingId: '4',
                playerKey: 'test',
                matching: [
                    {
                        events: listOfMatchingEvents,
                    },
                ],
            })
            logic.mount()
            await expectLogic(logic).toMatchValues({
                matching: [
                    {
                        events: listOfMatchingEvents,
                    },
                ],
            })
            logic = sessionRecordingPlayerLogic({
                sessionRecordingId: '4',
                playerKey: 'test',
                matching: [
                    {
                        events: [listOfMatchingEvents[0]],
                    },
                ],
            })
            logic.mount()
            await expectLogic(logic)
                .toDispatchActions(['setMatching'])
                .toMatchValues({
                    matching: [
                        {
                            events: [listOfMatchingEvents[0]],
                        },
                    ],
                })
        })
    })
})
