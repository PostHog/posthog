import { initKeaTests } from '~/test/init'
import { expectLogic } from 'kea-test-utils'
import { sessionRecordingLogic } from 'scenes/session-recordings/sessionRecordingLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { consoleLogsListLogic } from 'scenes/session-recordings/player/consoleLogsListLogic'
import { useMocks } from '~/mocks/jest'
import recordingSnapshotsJson from 'scenes/session-recordings/__mocks__/recording_snapshots.json'
import recordingMetaJson from 'scenes/session-recordings/__mocks__/recording_meta.json'
import recordingEventsJson from 'scenes/session-recordings/__mocks__/recording_events.json'
import { ConsoleFeedbackOptionValue } from '~/types'

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
            await expectLogic(logic).toMount([sessionRecordingLogic, eventUsageLogic])
        })
    })

    describe('feedback', () => {
        it('submit feedback works', async () => {
            await expectLogic(logic).toMatchValues({
                feedbackSubmitted: false,
            })
            await expectLogic(logic, () => {
                logic.actions.submitFeedback(ConsoleFeedbackOptionValue.Yes)
            })
                .toDispatchActions([
                    logic.actionCreators.submitFeedback(ConsoleFeedbackOptionValue.Yes),
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
                sessionRecordingLogic.actions.loadRecordingSnapshots('1')
                sessionRecordingLogic.actions.loadRecordingMeta('1')
            })
                .toDispatchActionsInAnyOrder([
                    sessionRecordingLogic.actionTypes.loadRecordingSnapshots,
                    sessionRecordingLogic.actionTypes.loadRecordingSnapshotsSuccess,
                    sessionRecordingLogic.actionTypes.loadRecordingMeta,
                    sessionRecordingLogic.actionTypes.loadRecordingMetaSuccess,
                ])
                .toMatchValues({
                    consoleLogs: [
                        // Empty payload object
                        {
                            level: undefined,
                            parsedPayload: undefined,
                            parsedTraceString: undefined,
                            parsedTraceURL: undefined,
                            playerPosition: {
                                time: 167777,
                                windowId: '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f',
                            },
                        },
                        // Empty trace and payload arrays
                        {
                            level: 'log',
                            parsedPayload: '',
                            parsedTraceString: undefined,
                            parsedTraceURL: undefined,
                            playerPosition: {
                                time: 167777,
                                windowId: '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f',
                            },
                        },
                        // Payload has null object
                        {
                            level: 'log',
                            parsedPayload: '',
                            parsedTraceString: 'file.js:123:456',
                            parsedTraceURL: 'https://example.com/path/to/file.js',
                            playerPosition: {
                                time: 167777,
                                windowId: '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f',
                            },
                        },
                        // Normal trace and payload
                        {
                            level: 'warn',
                            parsedPayload: 'A big deal And a huge deal',
                            parsedTraceString: 'file.js:123:456',
                            parsedTraceURL: 'https://example.com/path/to/file.js',
                            playerPosition: {
                                time: 167777,
                                windowId: '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f',
                            },
                        },
                        // Bad data trace and payload
                        {
                            level: 'error',
                            parsedPayload: undefined,
                            parsedTraceString: ':adcfvertyu$rf3423',
                            parsedTraceURL: '',
                            playerPosition: {
                                time: 167777,
                                windowId: '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f',
                            },
                        },
                    ],
                })
        })
    })
})
