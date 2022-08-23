import { initKeaTests } from '~/test/init'
import { expectLogic } from 'kea-test-utils'
import { sessionRecordingDataLogic } from 'scenes/session-recordings/player/sessionRecordingDataLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { consoleLogsListLogic } from 'scenes/session-recordings/player/consoleLogsListLogic'
import { sharedListLogic } from 'scenes/session-recordings/player/sharedListLogic'
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
            await expectLogic(logic).toMount([sessionRecordingDataLogic, eventUsageLogic, sharedListLogic])
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
                    sessionRecordingDataLogic.actionTypes.loadRecordingSnapshotsSuccess,
                    sessionRecordingDataLogic.actionTypes.loadRecordingMetaSuccess,
                ])
                .toMatchValues({
                    consoleLogs: [
                        '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f',
                        '182830cdf4b28a9-02530f1179ed36-1c525635-384000-182830cdf4c2841',
                    ]
                        .map((windowId) => [
                            // Empty payload object
                            expect.objectContaining({
                                level: undefined,
                                parsedPayload: undefined,
                                parsedTraceString: undefined,
                                parsedTraceURL: undefined,
                                playerPosition: {
                                    time: 167777,
                                    windowId,
                                },
                            }),
                            // Empty trace and payload arrays
                            expect.objectContaining({
                                level: 'log',
                                parsedPayload: '',
                                parsedTraceString: undefined,
                                parsedTraceURL: undefined,
                                playerPosition: {
                                    time: 167777,
                                    windowId,
                                },
                            }),
                            // Payload has null object
                            expect.objectContaining({
                                level: 'log',
                                parsedPayload: '',
                                parsedTraceString: 'file.js:123:456',
                                parsedTraceURL: 'https://example.com/path/to/file.js',
                                playerPosition: {
                                    time: 167777,
                                    windowId,
                                },
                            }),
                            // Normal trace and payload
                            expect.objectContaining({
                                level: 'warn',
                                parsedPayload: 'A big deal And a huge deal',
                                parsedTraceString: 'file.js:123:456',
                                parsedTraceURL: 'https://example.com/path/to/file.js',
                                playerPosition: {
                                    time: 167777,
                                    windowId,
                                },
                            }),
                            // Bad data trace and payload
                            expect.objectContaining({
                                level: 'error',
                                parsedPayload: undefined,
                                parsedTraceString: ':adcfvertyu$rf3423',
                                parsedTraceURL: '',
                                playerPosition: {
                                    time: 167777,
                                    windowId,
                                },
                            }),
                        ])
                        .flat(),
                })
        })

        it('should filter logs by specified window id', async () => {
            await expectLogic(logic, () => {
                sessionRecordingDataLogic.actions.loadRecordingSnapshots('1')
                sessionRecordingDataLogic.actions.loadRecordingMeta('1')
                sharedListLogic.actions.setWindowIdFilter(
                    '182830cdf4b28a9-02530f1179ed36-1c525635-384000-182830cdf4c2841'
                )
            })
                .toDispatchActionsInAnyOrder([
                    sessionRecordingDataLogic.actionTypes.loadRecordingSnapshotsSuccess,
                    sessionRecordingDataLogic.actionTypes.loadRecordingMetaSuccess,
                    sharedListLogic.actionTypes.setWindowIdFilter,
                ])
                .toMatchValues({
                    consoleLogs: ['182830cdf4b28a9-02530f1179ed36-1c525635-384000-182830cdf4c2841']
                        .map((windowId) => [
                            // Empty payload object
                            expect.objectContaining({
                                level: undefined,
                                parsedPayload: undefined,
                                parsedTraceString: undefined,
                                parsedTraceURL: undefined,
                                playerPosition: {
                                    time: 167777,
                                    windowId,
                                },
                            }),
                            // Empty trace and payload arrays
                            expect.objectContaining({
                                level: 'log',
                                parsedPayload: '',
                                parsedTraceString: undefined,
                                parsedTraceURL: undefined,
                                playerPosition: {
                                    time: 167777,
                                    windowId,
                                },
                            }),
                            // Payload has null object
                            expect.objectContaining({
                                level: 'log',
                                parsedPayload: '',
                                parsedTraceString: 'file.js:123:456',
                                parsedTraceURL: 'https://example.com/path/to/file.js',
                                playerPosition: {
                                    time: 167777,
                                    windowId,
                                },
                            }),
                            // Normal trace and payload
                            expect.objectContaining({
                                level: 'warn',
                                parsedPayload: 'A big deal And a huge deal',
                                parsedTraceString: 'file.js:123:456',
                                parsedTraceURL: 'https://example.com/path/to/file.js',
                                playerPosition: {
                                    time: 167777,
                                    windowId,
                                },
                            }),
                            // Bad data trace and payload
                            expect.objectContaining({
                                level: 'error',
                                parsedPayload: undefined,
                                parsedTraceString: ':adcfvertyu$rf3423',
                                parsedTraceURL: '',
                                playerPosition: {
                                    time: 167777,
                                    windowId,
                                },
                            }),
                        ])
                        .flat(),
                })
        })
    })
})
