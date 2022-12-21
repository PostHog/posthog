import { initKeaTests } from '~/test/init'
import { expectLogic } from 'kea-test-utils'
import { sessionRecordingDataLogic } from 'scenes/session-recordings/player/sessionRecordingDataLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { playerInspectorLogic } from 'scenes/session-recordings/player/inspector/playerInspectorLogic'
import { useMocks } from '~/mocks/jest'
import recordingSnapshotsJson from 'scenes/session-recordings/__mocks__/recording_snapshots.json'
import recordingMetaJson from 'scenes/session-recordings/__mocks__/recording_meta.json'
import recordingEventsJson from 'scenes/session-recordings/__mocks__/recording_events.json'
import { YesOrNoResponse } from '~/types'
import { consoleLogsListLogic } from './consoleLogsListLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

const playerLogicProps = { sessionRecordingId: '1', playerKey: 'playlist' }

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
        featureFlagLogic().mount()

        logic = consoleLogsListLogic(playerLogicProps)
        logic.mount()
    })

    describe('core assumptions', () => {
        it('mounts other logics', async () => {
            await expectLogic(logic).toMount([
                sessionRecordingDataLogic(playerLogicProps),
                eventUsageLogic(playerLogicProps),
                playerInspectorLogic(playerLogicProps),
            ])
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
                sessionRecordingDataLogic({ sessionRecordingId: '1' }).actions.loadRecordingSnapshots()
                sessionRecordingDataLogic({ sessionRecordingId: '1' }).actions.loadRecordingMeta()
            })
                .toDispatchActionsInAnyOrder([
                    sessionRecordingDataLogic({ sessionRecordingId: '1' }).actionTypes.loadRecordingSnapshotsSuccess,
                    sessionRecordingDataLogic({ sessionRecordingId: '1' }).actionTypes.loadRecordingMetaSuccess,
                ])
                .toMatchValues({
                    consoleListData: [
                        '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f',
                        '182830cdf4b28a9-02530f1179ed36-1c525635-384000-182830cdf4c2841',
                    ]
                        .map((windowId) => [
                            // Empty payload object
                            expect.objectContaining({
                                level: undefined,
                                parsedPayload: '',
                                playerPosition: {
                                    time: 167777,
                                    windowId,
                                },
                            }),
                            // Empty trace and payload arrays
                            expect.objectContaining({
                                level: 'log',
                                parsedPayload: '',
                                playerPosition: {
                                    time: 167777,
                                    windowId,
                                },
                            }),
                            // Payload has null object
                            expect.objectContaining({
                                level: 'log',
                                parsedPayload: '',
                                playerPosition: {
                                    time: 167777,
                                    windowId,
                                },
                            }),
                            // Normal trace and payload
                            expect.objectContaining({
                                level: 'warn',
                                parsedPayload: 'A big deal And a huge deal',
                                playerPosition: {
                                    time: 167777,
                                    windowId,
                                },
                            }),
                            // Bad data trace and payload
                            expect.objectContaining({
                                level: 'error',
                                parsedPayload: '',
                                playerPosition: {
                                    time: 167777,
                                    windowId,
                                },
                            }),
                        ])
                        .flat(),
                })
        })

        it('should filter events by fuzzy query', async () => {
            await expectLogic(logic, () => {
                sessionRecordingDataLogic({ sessionRecordingId: '1' }).actions.loadRecordingSnapshots()
                sessionRecordingDataLogic({ sessionRecordingId: '1' }).actions.loadRecordingMeta()
                sessionRecordingDataLogic({ sessionRecordingId: '1' }).actions.setFilters({ query: 'deal' })
            })
                .toDispatchActionsInAnyOrder([
                    sessionRecordingDataLogic({ sessionRecordingId: '1' }).actionTypes.loadRecordingSnapshotsSuccess,
                    sessionRecordingDataLogic({ sessionRecordingId: '1' }).actionTypes.loadEventsSuccess,
                    sessionRecordingDataLogic({ sessionRecordingId: '1' }).actionTypes.setFilters,
                ])
                .toMatchValues({
                    consoleListData: [
                        expect.objectContaining({
                            level: 'warn',
                            parsedPayload: 'A big deal And a huge deal',
                            playerPosition: {
                                time: 167777,
                                windowId: '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f',
                            },
                        }),
                        expect.objectContaining({
                            level: 'warn',
                            parsedPayload: 'A big deal And a huge deal',
                            playerPosition: {
                                time: 167777,
                                windowId: '182830cdf4b28a9-02530f1179ed36-1c525635-384000-182830cdf4c2841',
                            },
                        }),
                    ],
                })
        })

        it('should filter logs by specified window id', async () => {
            await expectLogic(logic, () => {
                sessionRecordingDataLogic({ sessionRecordingId: '1' }).actions.loadRecordingSnapshots()
                sessionRecordingDataLogic({ sessionRecordingId: '1' }).actions.loadRecordingMeta()
                playerInspectorLogic(playerLogicProps).actions.setWindowIdFilter(
                    '182830cdf4b28a9-02530f1179ed36-1c525635-384000-182830cdf4c2841'
                )
            })
                .toDispatchActionsInAnyOrder([
                    sessionRecordingDataLogic({ sessionRecordingId: '1' }).actionTypes.loadRecordingSnapshotsSuccess,
                    sessionRecordingDataLogic({ sessionRecordingId: '1' }).actionTypes.loadRecordingMetaSuccess,
                    playerInspectorLogic(playerLogicProps).actionTypes.setWindowIdFilter,
                ])
                .toMatchValues({
                    consoleListData: ['182830cdf4b28a9-02530f1179ed36-1c525635-384000-182830cdf4c2841']
                        .map((windowId) => [
                            // Empty payload object
                            expect.objectContaining({
                                level: undefined,
                                parsedPayload: '',
                                playerPosition: {
                                    time: 167777,
                                    windowId,
                                },
                            }),
                            // Empty trace and payload arrays
                            expect.objectContaining({
                                level: 'log',
                                parsedPayload: '',
                                playerPosition: {
                                    time: 167777,
                                    windowId,
                                },
                            }),
                            // Payload has null object
                            expect.objectContaining({
                                level: 'log',
                                parsedPayload: '',
                                playerPosition: {
                                    time: 167777,
                                    windowId,
                                },
                            }),
                            // Normal trace and payload
                            expect.objectContaining({
                                level: 'warn',
                                parsedPayload: 'A big deal And a huge deal',
                                playerPosition: {
                                    time: 167777,
                                    windowId,
                                },
                            }),
                            // Bad data trace and payload
                            expect.objectContaining({
                                level: 'error',
                                parsedPayload: '',
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

    describe('setConsoleListLocalFilters', () => {
        it('calls setFilter in parent logic with debounce', async () => {
            const filters = { query: 'mini pretzels' }
            await expectLogic(logic, () => {
                logic.actions.setConsoleListLocalFilters({ query: 'no mini pretzels' })
                logic.actions.setConsoleListLocalFilters(filters)
            })
                .toNotHaveDispatchedActions([
                    sessionRecordingDataLogic({ sessionRecordingId: '1' }).actionCreators.setFilters({
                        query: 'no mini pretzels',
                    }),
                ])
                .toDispatchActions([
                    sessionRecordingDataLogic({ sessionRecordingId: '1' }).actionCreators.setFilters(filters),
                ])
        })
    })
})
