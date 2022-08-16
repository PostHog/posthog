import { initKeaTests } from '~/test/init'
import { expectLogic } from 'kea-test-utils'
import { sessionRecordingDataLogic } from 'scenes/session-recordings/player/sessionRecordingDataLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { consoleLogsListLogic } from 'scenes/session-recordings/player/consoleLogsListLogic'
import { useMocks } from '~/mocks/jest'
import recordingSnapshotsJson from 'scenes/session-recordings/__mocks__/recording_snapshots.json'
import recordingMetaJson from 'scenes/session-recordings/__mocks__/recording_meta.json'
import recordingEventsJson from 'scenes/session-recordings/__mocks__/recording_events.json'
import { YesOrNoResponse } from '~/types'

describe('consoleLogsListLogic', () => {
    let logic: ReturnType<typeof consoleLogsListLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/session_recordings/:id/snapshots': { result: recordingSnapshotsJson },
                '/api/projects/:team/session_recordings/:id': { result: recordingMetaJson },
                '/api/projects/:team/events': { results: recordingEventsJson },
            },
        })
        initKeaTests()
        logic = consoleLogsListLogic()
        logic.mount()
    })

    describe('core assumptions', () => {
        it('mounts other logics', async () => {
            await expectLogic(logic).toMount([sessionRecordingDataLogic, eventUsageLogic])
        })
    })

    describe('feedback', () => {
        it('submit feedback works', async () => {
            await expectLogic(logic).toMatchValues({
                feedbackSubmitted: false,
            })
            await expectLogic(logic, () => {
                logic.actions.submitFeedback(YesOrNoResponse.Yes)
            })
                .toDispatchActions([
                    logic.actionCreators.submitFeedback(YesOrNoResponse.Yes),
                    eventUsageLogic.actionTypes.reportRecordingConsoleFeedback,
                ])
                .toMatchValues({
                    feedbackSubmitted: true,
                })
        })
    })

    describe('console logs', () => {
        it('should load and parse console logs from the snapshot', async () => {
            await expectLogic(logic, () => {
                sessionRecordingDataLogic.actions.loadRecordingSnapshots('1')
                sessionRecordingDataLogic.actions.loadRecordingMeta('1')
            })
                .toDispatchActionsInAnyOrder([
                    sessionRecordingDataLogic.actionTypes.loadRecordingSnapshots,
                    sessionRecordingDataLogic.actionTypes.loadRecordingSnapshotsSuccess,
                    sessionRecordingDataLogic.actionTypes.loadRecordingMeta,
                    sessionRecordingDataLogic.actionTypes.loadRecordingMetaSuccess,
                ])
                .toMatchValues({
                    consoleLogs: [
                        // Empty payload object
                        {
                            colonTimestamp: '00:02:47',
                            level: undefined,
                            parsedPayload: undefined,
                            parsedTraceString: undefined,
                            parsedTraceURL: undefined,
                            playerPosition: {
                                time: 167777,
                                windowId: '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f',
                            },
                            playerTime: 167772,
                        },
                        // Empty trace and payload arrays
                        {
                            colonTimestamp: '00:02:47',
                            level: 'log',
                            parsedPayload: '',
                            parsedTraceString: undefined,
                            parsedTraceURL: undefined,
                            playerPosition: {
                                time: 167777,
                                windowId: '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f',
                            },
                            playerTime: 167772,
                        },
                        // Payload has null object
                        {
                            colonTimestamp: '00:02:47',
                            level: 'log',
                            parsedPayload: '',
                            parsedTraceString: 'file.js:123:456',
                            parsedTraceURL: 'https://example.com/path/to/file.js',
                            playerPosition: {
                                time: 167777,
                                windowId: '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f',
                            },
                            playerTime: 167772,
                        },
                        // Normal trace and payload
                        {
                            colonTimestamp: '00:02:47',
                            level: 'warn',
                            parsedPayload: 'A big deal And a huge deal',
                            parsedTraceString: 'file.js:123:456',
                            parsedTraceURL: 'https://example.com/path/to/file.js',
                            playerPosition: {
                                time: 167777,
                                windowId: '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f',
                            },
                            playerTime: 167772,
                        },
                        // Bad data trace and payload
                        {
                            colonTimestamp: '00:02:47',
                            level: 'error',
                            parsedPayload: undefined,
                            parsedTraceString: ':adcfvertyu$rf3423',
                            parsedTraceURL: '',
                            playerPosition: {
                                time: 167777,
                                windowId: '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f',
                            },
                            playerTime: 167772,
                        },
                    ],
                })
        })
    })
})
