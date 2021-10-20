import { sessionsPlayLogic } from 'scenes/sessions/sessionsPlayLogic'
import { api, defaultAPIMocks, mockAPI, MOCK_TEAM_ID } from 'lib/api.mock'
import { expectLogic } from 'kea-test-utils'
import { initKeaTestLogic } from '~/test/init'
import { sessionsTableLogic } from 'scenes/sessions/sessionsTableLogic'
import { eventUsageLogic, RecordingWatchedSource } from 'lib/utils/eventUsageLogic'
import recordingJson from './__mocks__/recording.json'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { combineUrl } from 'kea-router'

jest.mock('lib/api')

const EVENTS_SESSION_RECORDING_ENDPOINT = `api/projects/${MOCK_TEAM_ID}/events/session_recording`

describe('sessionsPlayLogic', () => {
    let logic: ReturnType<typeof sessionsPlayLogic.build>

    mockAPI(async (url) => {
        if (
            url.pathname === EVENTS_SESSION_RECORDING_ENDPOINT || // Old api
            url.pathname === `api/projects/${MOCK_TEAM_ID}/session_recordings` // New api
        ) {
            return { result: recordingJson }
        } else if (url.pathname === 'api/sessions_filter') {
            return { results: [] }
        }
        return defaultAPIMocks(url)
    })

    initKeaTestLogic({
        logic: sessionsPlayLogic,
        onLogic: (l) => (logic = l),
    })

    describe('core assumptions', () => {
        it('mounts other logics', async () => {
            await expectLogic(logic).toMount([sessionsTableLogic, eventUsageLogic])
        })
        it('has default values', async () => {
            await expectLogic(logic).toMatchValues({
                sessionRecordingId: null,
                sessionPlayerData: null,
                addingTagShown: false,
                addingTag: '',
                loadingNextRecording: false,
                firstChunkLoaded: false,
                source: RecordingWatchedSource.Unknown,
            })
        })
    })

    describe('loading session data', () => {
        it('no next url', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadRecording('1')
            })
                .toDispatchActions(['loadRecording', 'loadRecordingSuccess'])
                .toMatchValues({
                    sessionPlayerData: recordingJson,
                })
                .toNotHaveDispatchedActions(['loadRecording'])
        })
        it('fetch all chunks of recording', async () => {
            await expectLogic(preflightLogic).toDispatchActions(['loadPreflightSuccess'])
            await expectLogic(logic).toMount([eventUsageLogic])
            api.get.mockClear()

            const firstNext = `${EVENTS_SESSION_RECORDING_ENDPOINT}?session_recording_id=1&offset=200&limit=200`
            const secondNext = `${EVENTS_SESSION_RECORDING_ENDPOINT}?session_recording_id=1&offset=400&limit=200`
            const thirdNext = `${EVENTS_SESSION_RECORDING_ENDPOINT}?session_recording_id=1&offset=600&limit=200`
            const snaps = recordingJson.snapshots

            api.get
                .mockImplementationOnce(async (url: string) => {
                    if (combineUrl(url).pathname === EVENTS_SESSION_RECORDING_ENDPOINT) {
                        return { result: { ...recordingJson, next: firstNext } }
                    }
                })
                .mockImplementationOnce(async (url: string) => {
                    if (combineUrl(url).pathname === EVENTS_SESSION_RECORDING_ENDPOINT) {
                        return { result: { ...recordingJson, next: secondNext } }
                    }
                })
                .mockImplementationOnce(async (url: string) => {
                    if (combineUrl(url).pathname === EVENTS_SESSION_RECORDING_ENDPOINT) {
                        return { result: { ...recordingJson, next: thirdNext } }
                    }
                })
                .mockImplementationOnce(async (url: string) => {
                    if (combineUrl(url).pathname === EVENTS_SESSION_RECORDING_ENDPOINT) {
                        return { result: recordingJson }
                    }
                })

            await expectLogic(logic, () => {
                logic.actions.loadRecording('1')
            })
                .toDispatchActions(['loadRecordingSuccess'])
                .toMatchValues({
                    sessionPlayerData: { ...recordingJson, next: firstNext },
                })
                .toDispatchActions([logic.actionCreators.loadRecording(undefined, firstNext), 'loadRecordingSuccess'])
                .toMatchValues({
                    sessionPlayerData: {
                        ...recordingJson,
                        next: secondNext,
                        snapshots: [...snaps, ...snaps],
                    },
                })
                .toDispatchActions([logic.actionCreators.loadRecording(undefined, secondNext), 'loadRecordingSuccess'])
                .toMatchValues({
                    sessionPlayerData: {
                        ...recordingJson,
                        next: thirdNext,
                        snapshots: [...snaps, ...snaps, ...snaps],
                    },
                })
                .toDispatchActions([logic.actionCreators.loadRecording(undefined, thirdNext), 'loadRecordingSuccess'])
                .toMatchValues({
                    sessionPlayerData: {
                        ...recordingJson,
                        next: null,
                        snapshots: [...snaps, ...snaps, ...snaps, ...snaps],
                    },
                })

            expect(api.get).toBeCalledTimes(4)
        })
        it('internal server error mid-way through recording', async () => {
            await expectLogic(preflightLogic).toDispatchActions(['loadPreflightSuccess'])
            await expectLogic(logic).toMount([eventUsageLogic])
            api.get.mockClear()

            const firstNext = `${EVENTS_SESSION_RECORDING_ENDPOINT}?session_recording_id=1&offset=200&limit=200`
            const secondNext = `${EVENTS_SESSION_RECORDING_ENDPOINT}?session_recording_id=1&offset=400&limit=200`
            const snaps = recordingJson.snapshots

            api.get
                .mockImplementationOnce(async (url: string) => {
                    if (combineUrl(url).pathname === EVENTS_SESSION_RECORDING_ENDPOINT) {
                        return { result: { ...recordingJson, next: firstNext } }
                    }
                })
                .mockImplementationOnce(async (url: string) => {
                    if (combineUrl(url).pathname === EVENTS_SESSION_RECORDING_ENDPOINT) {
                        return { result: { ...recordingJson, next: secondNext } }
                    }
                })
                .mockImplementationOnce(async () => {
                    throw new Error('Error in third request')
                })

            await expectLogic(logic, () => {
                logic.actions.loadRecording('1')
            })
                .toDispatchActions(['loadRecordingSuccess'])
                .toMatchValues({
                    sessionPlayerData: { ...recordingJson, next: firstNext },
                    firstChunkLoaded: true,
                })
                .toDispatchActions([logic.actionCreators.loadRecording(undefined, firstNext), 'loadRecordingSuccess'])
                .toMatchValues({
                    sessionPlayerData: {
                        ...recordingJson,
                        next: secondNext,
                        snapshots: [...snaps, ...snaps],
                    },
                    firstChunkLoaded: true,
                })
                .toDispatchActions([logic.actionCreators.loadRecording(undefined, secondNext), 'loadRecordingFailure'])

            // Error toast is thrown
            expect(api.get).toBeCalledTimes(3)
        })
    })

    describe('loading states', () => {
        it('standard loading in single chunk recording', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadRecording('1')
            })
                .toDispatchActions(['loadRecording'])
                .toMatchValues({
                    firstChunkLoaded: false,
                    sessionPlayerDataLoading: true,
                })
                .toDispatchActions(['loadRecordingSuccess'])
                .toMatchValues({
                    firstChunkLoaded: true,
                    sessionPlayerDataLoading: false,
                })
                .toNotHaveDispatchedActions(['loadRecording'])
        })
        it('stays loading throughout multi chunk recording', async () => {
            await expectLogic(preflightLogic).toDispatchActions(['loadPreflightSuccess'])
            await expectLogic(logic).toMount([eventUsageLogic])

            const firstNext = `${EVENTS_SESSION_RECORDING_ENDPOINT}?session_recording_id=1&offset=200&limit=200`
            const secondNext = `${EVENTS_SESSION_RECORDING_ENDPOINT}?session_recording_id=1&offset=400&limit=200`

            api.get
                .mockImplementationOnce(async (url: string) => {
                    if (combineUrl(url).pathname === EVENTS_SESSION_RECORDING_ENDPOINT) {
                        return { result: { ...recordingJson, next: firstNext } }
                    }
                })
                .mockImplementationOnce(async (url: string) => {
                    if (combineUrl(url).pathname === EVENTS_SESSION_RECORDING_ENDPOINT) {
                        return { result: { ...recordingJson, next: secondNext } }
                    }
                })
                .mockImplementationOnce(async (url: string) => {
                    if (combineUrl(url).pathname === EVENTS_SESSION_RECORDING_ENDPOINT) {
                        return { result: recordingJson }
                    }
                })

            await expectLogic(logic, () => {
                logic.actions.loadRecording('1')
            })
                .toDispatchActions(['loadRecording'])
                .toMatchValues({
                    firstChunkLoaded: false,
                    sessionPlayerDataLoading: true,
                })
                .toDispatchActions(['loadRecordingSuccess'])
                .toMatchValues({
                    firstChunkLoaded: true,
                    sessionPlayerDataLoading: true,
                })
                .toDispatchActions([logic.actionCreators.loadRecording(undefined, firstNext)])
                .toMatchValues({
                    firstChunkLoaded: true,
                    sessionPlayerDataLoading: true,
                })
                .toDispatchActions(['loadRecordingSuccess'])
                .toMatchValues({
                    firstChunkLoaded: true,
                    sessionPlayerDataLoading: true,
                })
                .toDispatchActions([logic.actionCreators.loadRecording(undefined, secondNext)])
                .toMatchValues({
                    firstChunkLoaded: true,
                    sessionPlayerDataLoading: true,
                })
                .toDispatchActions(['loadRecordingSuccess'])
                .toMatchValues({
                    firstChunkLoaded: true,
                    sessionPlayerDataLoading: false,
                })
        })
        describe('isPlayable', () => {
            it('first chunk loads but no full snapshot yet', async () => {
                await expectLogic(logic, () => {
                    logic.actions.loadRecording('1')
                })
                    .toDispatchActions(['loadRecording', 'loadRecordingSuccess'])
                    .toMatchValues({
                        sessionPlayerData: recordingJson,
                        firstChunkLoaded: true,
                        isPlayable: false,
                    })
            })
            it("first chunk loads and there's at least one full snapshot", async () => {
                const newSnapshots = [
                    ...recordingJson.snapshots,
                    {
                        type: 2,
                        data: { source: 0 },
                        timestamp: 1634019260528,
                    },
                ]
                api.get.mockImplementationOnce(async (url: string) => {
                    if (combineUrl(url).pathname === EVENTS_SESSION_RECORDING_ENDPOINT) {
                        return {
                            result: {
                                ...recordingJson,
                                snapshots: newSnapshots,
                            },
                        }
                    }
                })

                await expectLogic(logic, () => {
                    logic.actions.loadRecording('1')
                })
                    .toDispatchActions(['loadRecording', 'loadRecordingSuccess'])
                    .toMatchValues({
                        sessionPlayerData: { ...recordingJson, snapshots: newSnapshots },
                        firstChunkLoaded: true,
                        isPlayable: true,
                    })
            })
            it('session player data is still loading', async () => {
                const newSnapshots = [
                    ...recordingJson.snapshots,
                    {
                        type: 2,
                        data: { source: 0 },
                        timestamp: 1634019260528,
                    },
                ]
                api.get.mockImplementationOnce(async (url: string) => {
                    if (combineUrl(url).pathname === EVENTS_SESSION_RECORDING_ENDPOINT) {
                        return {
                            result: {
                                ...recordingJson,
                                snapshots: newSnapshots,
                            },
                        }
                    }
                })

                await expectLogic(logic, () => {
                    logic.actions.loadRecording('1')
                })
                    .toDispatchActions(['loadRecording'])
                    .toMatchValues({
                        firstChunkLoaded: false,
                        isPlayable: false,
                    })
                    .toDispatchActions(['loadRecordingSuccess'])
                    .toMatchValues({
                        sessionPlayerData: { ...recordingJson, snapshots: newSnapshots },
                        firstChunkLoaded: true,
                        isPlayable: true,
                    })
            })
        })
    })
})
