import { parseMetadataResponse, sessionRecordingLogic } from 'scenes/session-recordings/sessionRecordingLogic'
import { api, defaultAPIMocks, mockAPI, MOCK_TEAM_ID } from 'lib/api.mock'
import { expectLogic } from 'kea-test-utils'
import { initKeaTestLogic } from '~/test/init'
import { eventUsageLogic, RecordingWatchedSource } from 'lib/utils/eventUsageLogic'
import recordingSnapshotsJson from './__mocks__/recording_snapshots.json'
import recordingMetaJson from './__mocks__/recording_meta.json'
import recordingEventsJson from './__mocks__/recording_events.json'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { combineUrl } from 'kea-router'

jest.mock('lib/api')

const createSnapshotEndpoint = (id: number): string => `api/projects/${MOCK_TEAM_ID}/session_recordings/${id}/snapshots`
const EVENTS_SESSION_RECORDING_SNAPSHOTS_ENDPOINT_REGEX = new RegExp(
    `api/projects/${MOCK_TEAM_ID}/session_recordings/\\d/snapshots`
)
const EVENTS_SESSION_RECORDING_META_ENDPOINT = `api/projects/${MOCK_TEAM_ID}/session_recordings`
const EVENTS_SESSION_RECORDING_EVENTS_ENDPOINT = `api/projects/${MOCK_TEAM_ID}/events`

describe('sessionRecordingLogic', () => {
    let logic: ReturnType<typeof sessionRecordingLogic.build>

    mockAPI(async (url) => {
        if (!!url.pathname.match(EVENTS_SESSION_RECORDING_SNAPSHOTS_ENDPOINT_REGEX)) {
            return { result: recordingSnapshotsJson }
        } else if (url.pathname.startsWith(EVENTS_SESSION_RECORDING_META_ENDPOINT)) {
            return { result: recordingMetaJson }
        } else if (url.pathname.startsWith(EVENTS_SESSION_RECORDING_EVENTS_ENDPOINT)) {
            return { results: recordingEventsJson }
        }
        return defaultAPIMocks(url)
    })

    initKeaTestLogic({
        logic: sessionRecordingLogic,
        onLogic: (l) => (logic = l),
    })

    describe('core assumptions', () => {
        it('mounts other logics', async () => {
            await expectLogic(logic).toMount([eventUsageLogic])
        })
        it('has default values', async () => {
            await expectLogic(logic).toMatchValues({
                sessionRecordingId: null,
                sessionPlayerData: null,
                firstChunkLoaded: false,
                source: RecordingWatchedSource.Unknown,
            })
        })
    })

    describe('loading session core', () => {
        it('fetch metadata and snapshots together', async () => {
            const firstPayload = {
                ...recordingMetaJson,
                session_recording: parseMetadataResponse(recordingMetaJson.session_recording),
                snapshots: [],
            }
            const secondPayload = {
                ...firstPayload,
                next: undefined,
                snapshots: recordingSnapshotsJson.snapshots,
            }
            await expectLogic(logic, () => {
                logic.actions.loadRecordingMeta('1')
            })
                .toDispatchActions(['loadRecordingMeta', 'loadRecordingMetaSuccess'])
                .toMatchValues({
                    sessionPlayerData: firstPayload,
                })
                .toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.loadRecordingSnapshots('1')
            })
                .toDispatchActions(['loadRecordingSnapshots', 'loadRecordingSnapshotsSuccess'])
                .toMatchValues({
                    sessionPlayerData: secondPayload,
                })
        })
        it('fetch metadata error and snapshots success', async () => {
            api.get.mockImplementation(async (url: string) => {
                if (combineUrl(url).pathname.match(EVENTS_SESSION_RECORDING_SNAPSHOTS_ENDPOINT_REGEX)) {
                    return { result: { ...recordingSnapshotsJson, next: undefined } }
                } else {
                    throw new Error('Oh no.')
                }
            })
            await expectLogic(logic, () => {
                logic.actions.loadRecordingMeta('1')
            })
                .toDispatchActions(['loadRecordingMeta', 'loadRecordingMetaFailure'])
                .toMatchValues({
                    sessionPlayerData: null,
                })
                .toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.loadRecordingSnapshots('1')
            })
                .toDispatchActions(['loadRecordingSnapshots', 'loadRecordingSnapshotsSuccess'])
                .toMatchValues({
                    sessionPlayerData: {
                        next: undefined,
                        snapshots: recordingSnapshotsJson.snapshots,
                    },
                })
        })
        it('fetch metadata success and snapshots error', async () => {
            const expected = {
                ...recordingMetaJson,
                session_recording: parseMetadataResponse(recordingMetaJson.session_recording),
                snapshots: [],
            }
            api.get.mockImplementation(async (url: string) => {
                if (combineUrl(url).pathname.match(EVENTS_SESSION_RECORDING_SNAPSHOTS_ENDPOINT_REGEX)) {
                    throw new Error('Oh no.')
                } else {
                    return { result: recordingMetaJson }
                }
            })
            await expectLogic(logic, () => {
                logic.actions.loadRecordingMeta('1')
            })
                .toDispatchActions(['loadRecordingMeta', 'loadRecordingMetaSuccess'])
                .toMatchValues({
                    sessionPlayerData: expected,
                })
                .toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.loadRecordingSnapshots('1')
            })
                .toDispatchActions(['loadRecordingSnapshots', 'loadRecordingSnapshotsFailure'])
                .toMatchValues({
                    sessionPlayerData: expected,
                })
        })
    })

    describe('loading session events', () => {
        it('load events after metadata with 1min buffer', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadRecordingMeta('1')
            })
                .toDispatchActions(['loadRecordingMeta', 'loadRecordingMetaSuccess', 'loadEvents'])
                .toMatchValues({
                    eventsApiParams: {
                        after: '2021-10-12T05:12:42Z',
                        before: '2021-10-12T18:48:47Z',
                        person_id: 1,
                        orderBy: ['timestamp'],
                    },
                })
        })
        it('no next url', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadRecordingMeta('1')
            })
                .toDispatchActions(['loadRecordingMeta', 'loadRecordingMetaSuccess', 'loadEvents', 'loadEventsSuccess'])
                .toNotHaveDispatchedActions(['loadEvents'])
        })
        it('fetch all events', async () => {
            const firstNext = `${EVENTS_SESSION_RECORDING_EVENTS_ENDPOINT}?person_id=1&before=2021-10-28T17:45:12.128000Z&after=2021-10-28T16:45:05Z`
            const secondNext = `${EVENTS_SESSION_RECORDING_EVENTS_ENDPOINT}?person_id=1&before=2021-10-28T17:45:12.128000Z&after=2021-10-28T16:50:05Z`
            const thirdNext = `${EVENTS_SESSION_RECORDING_EVENTS_ENDPOINT}?person_id=1&before=2021-10-28T17:45:12.128000Z&after=2021-10-28T17:00:05Z`
            const events = recordingEventsJson

            api.get.mockClear()
            api.get
                .mockImplementationOnce(async (url: string) => {
                    if (combineUrl(url).pathname.startsWith(EVENTS_SESSION_RECORDING_META_ENDPOINT)) {
                        return { result: recordingMetaJson }
                    }
                })
                .mockImplementationOnce(async (url: string) => {
                    if (combineUrl(url).pathname.startsWith(EVENTS_SESSION_RECORDING_EVENTS_ENDPOINT)) {
                        return { results: recordingEventsJson, next: firstNext }
                    }
                })
                .mockImplementationOnce(async (url: string) => {
                    if (combineUrl(url).pathname.startsWith(EVENTS_SESSION_RECORDING_EVENTS_ENDPOINT)) {
                        return { results: recordingEventsJson, next: secondNext }
                    }
                })
                .mockImplementationOnce(async (url: string) => {
                    if (combineUrl(url).pathname.startsWith(EVENTS_SESSION_RECORDING_EVENTS_ENDPOINT)) {
                        return { results: recordingEventsJson, next: thirdNext }
                    }
                })
                .mockImplementationOnce(async (url: string) => {
                    if (combineUrl(url).pathname.match(EVENTS_SESSION_RECORDING_EVENTS_ENDPOINT)) {
                        return { results: recordingEventsJson }
                    }
                })

            await expectLogic(logic, () => {
                logic.actions.loadRecordingMeta('1')
            })
                .toDispatchActions(['loadRecordingMeta', 'loadRecordingMetaSuccess', 'loadEvents', 'loadEventsSuccess'])
                .toMatchValues({
                    sessionEventsData: {
                        next: firstNext,
                        events,
                    },
                })
                .toDispatchActions([logic.actionCreators.loadEvents(firstNext), 'loadEventsSuccess'])
                .toMatchValues({
                    sessionEventsData: {
                        next: secondNext,
                        events: [...events, ...events],
                    },
                })
                .toDispatchActions([logic.actionCreators.loadEvents(secondNext), 'loadEventsSuccess'])
                .toMatchValues({
                    sessionEventsData: {
                        next: thirdNext,
                        events: [...events, ...events, ...events],
                    },
                })
                .toDispatchActions([logic.actionCreators.loadEvents(thirdNext), 'loadEventsSuccess'])
                .toMatchValues({
                    sessionEventsData: {
                        next: undefined,
                        events: [...events, ...events, ...events, ...events],
                    },
                })
                .toNotHaveDispatchedActions(['loadEvents'])
            expect(api.get).toBeCalledTimes(5)
        })
        it('server error mid-fetch', async () => {
            const firstNext = `${EVENTS_SESSION_RECORDING_EVENTS_ENDPOINT}?person_id=1&before=2021-10-28T17:45:12.128000Z&after=2021-10-28T16:45:05Z`
            const secondNext = `${EVENTS_SESSION_RECORDING_EVENTS_ENDPOINT}?person_id=1&before=2021-10-28T17:45:12.128000Z&after=2021-10-28T16:50:05Z`
            const events = recordingEventsJson

            api.get.mockClear()
            api.get
                .mockImplementationOnce(async (url: string) => {
                    if (combineUrl(url).pathname.startsWith(EVENTS_SESSION_RECORDING_META_ENDPOINT)) {
                        return { result: recordingMetaJson }
                    }
                })
                .mockImplementationOnce(async (url: string) => {
                    if (combineUrl(url).pathname.startsWith(EVENTS_SESSION_RECORDING_EVENTS_ENDPOINT)) {
                        return { results: recordingEventsJson, next: firstNext }
                    }
                })
                .mockImplementationOnce(async (url: string) => {
                    if (combineUrl(url).pathname.startsWith(EVENTS_SESSION_RECORDING_EVENTS_ENDPOINT)) {
                        return { results: recordingEventsJson, next: secondNext }
                    }
                })
                .mockImplementationOnce(async () => {
                    throw new Error('Error in third request')
                })

            await expectLogic(logic, () => {
                logic.actions.loadRecordingMeta('1')
            })
                .toDispatchActions(['loadRecordingMeta', 'loadRecordingMetaSuccess', 'loadEvents', 'loadEventsSuccess'])
                .toMatchValues({
                    sessionEventsData: {
                        next: firstNext,
                        events,
                    },
                })
                .toDispatchActions([logic.actionCreators.loadEvents(firstNext), 'loadEventsSuccess'])
                .toMatchValues({
                    sessionEventsData: {
                        next: secondNext,
                        events: [...events, ...events],
                    },
                })
                .toDispatchActions([logic.actionCreators.loadEvents(secondNext), 'loadEventsFailure'])
            expect(api.get).toBeCalledTimes(4)
        })
    })

    describe('loading session snapshots', () => {
        it('no next url', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadRecordingSnapshots('1')
            })
                .toDispatchActions(['loadRecordingSnapshots', 'loadRecordingSnapshotsSuccess'])
                .toMatchValues({
                    sessionPlayerData: recordingSnapshotsJson,
                })
                .toNotHaveDispatchedActions(['loadRecordingSnapshots'])
        })
        it('fetch all chunks of recording', async () => {
            await expectLogic(preflightLogic).toDispatchActions(['loadPreflightSuccess'])
            await expectLogic(logic).toMount([eventUsageLogic])
            api.get.mockClear()

            const snapshotUrl = createSnapshotEndpoint(1)
            const firstNext = `${snapshotUrl}/?offset=200&limit=200`
            const secondNext = `${snapshotUrl}/?offset=400&limit=200`
            const thirdNext = `${snapshotUrl}/?offset=600&limit=200`
            const snaps = recordingSnapshotsJson.snapshots

            api.get
                .mockImplementationOnce(async (url: string) => {
                    if (combineUrl(url).pathname.match(EVENTS_SESSION_RECORDING_SNAPSHOTS_ENDPOINT_REGEX)) {
                        return { result: { ...recordingSnapshotsJson, next: firstNext } }
                    }
                })
                .mockImplementationOnce(async (url: string) => {
                    if (combineUrl(url).pathname.match(EVENTS_SESSION_RECORDING_SNAPSHOTS_ENDPOINT_REGEX)) {
                        return { result: { ...recordingSnapshotsJson, next: secondNext } }
                    }
                })
                .mockImplementationOnce(async (url: string) => {
                    if (combineUrl(url).pathname.match(EVENTS_SESSION_RECORDING_SNAPSHOTS_ENDPOINT_REGEX)) {
                        return { result: { ...recordingSnapshotsJson, next: thirdNext } }
                    }
                })
                .mockImplementationOnce(async (url: string) => {
                    if (combineUrl(url).pathname.match(EVENTS_SESSION_RECORDING_SNAPSHOTS_ENDPOINT_REGEX)) {
                        return { result: recordingSnapshotsJson }
                    }
                })

            await expectLogic(logic, () => {
                logic.actions.loadRecordingSnapshots('1')
            })
                .toDispatchActions(['loadRecordingSnapshots', 'loadRecordingSnapshotsSuccess'])
                .toMatchValues({
                    sessionPlayerData: { ...recordingSnapshotsJson, next: firstNext },
                })
                .toDispatchActions([
                    logic.actionCreators.loadRecordingSnapshots(undefined, firstNext),
                    'loadRecordingSnapshotsSuccess',
                ])
                .toMatchValues({
                    sessionPlayerData: {
                        ...recordingSnapshotsJson,
                        next: secondNext,
                        snapshots: [...snaps, ...snaps],
                    },
                })
                .toDispatchActions([
                    logic.actionCreators.loadRecordingSnapshots(undefined, secondNext),
                    'loadRecordingSnapshotsSuccess',
                ])
                .toMatchValues({
                    sessionPlayerData: {
                        ...recordingSnapshotsJson,
                        next: thirdNext,
                        snapshots: [...snaps, ...snaps, ...snaps],
                    },
                })
                .toDispatchActions([
                    logic.actionCreators.loadRecordingSnapshots(undefined, thirdNext),
                    'loadRecordingSnapshotsSuccess',
                ])
                .toMatchValues({
                    sessionPlayerData: {
                        ...recordingSnapshotsJson,
                        next: undefined,
                        snapshots: [...snaps, ...snaps, ...snaps, ...snaps],
                    },
                })

            expect(api.get).toBeCalledTimes(4)
        })
        it('server error mid-way through recording', async () => {
            await expectLogic(preflightLogic).toDispatchActions(['loadPreflightSuccess'])
            await expectLogic(logic).toMount([eventUsageLogic])
            api.get.mockClear()

            const snapshotUrl = createSnapshotEndpoint(1)
            const firstNext = `${snapshotUrl}/?offset=200&limit=200`
            const secondNext = `${snapshotUrl}/?offset=400&limit=200`
            const snaps = recordingSnapshotsJson.snapshots

            api.get
                .mockImplementationOnce(async (url: string) => {
                    if (combineUrl(url).pathname.match(EVENTS_SESSION_RECORDING_SNAPSHOTS_ENDPOINT_REGEX)) {
                        return { result: { ...recordingSnapshotsJson, next: firstNext } }
                    }
                })
                .mockImplementationOnce(async (url: string) => {
                    if (combineUrl(url).pathname.match(EVENTS_SESSION_RECORDING_SNAPSHOTS_ENDPOINT_REGEX)) {
                        return { result: { ...recordingSnapshotsJson, next: secondNext } }
                    }
                })
                .mockImplementationOnce(async () => {
                    throw new Error('Error in third request')
                })

            await expectLogic(logic, () => {
                logic.actions.loadRecordingSnapshots('1')
            })
                .toDispatchActions(['loadRecordingSnapshots', 'loadRecordingSnapshotsSuccess'])
                .toMatchValues({
                    sessionPlayerData: { ...recordingSnapshotsJson, next: firstNext },
                    firstChunkLoaded: true,
                })
                .toDispatchActions([
                    logic.actionCreators.loadRecordingSnapshots(undefined, firstNext),
                    'loadRecordingSnapshotsSuccess',
                ])
                .toMatchValues({
                    sessionPlayerData: {
                        ...recordingSnapshotsJson,
                        next: secondNext,
                        snapshots: [...snaps, ...snaps],
                    },
                    firstChunkLoaded: true,
                })
                .toDispatchActions([
                    logic.actionCreators.loadRecordingSnapshots(undefined, secondNext),
                    'loadRecordingSnapshotsFailure',
                ])

            // Error toast is thrown
            expect(api.get).toBeCalledTimes(3)
        })
    })

    describe('loading states', () => {
        it('meta and snapshots loaded together', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadRecordingMeta('1')
            })
                .toDispatchActions(['loadRecordingMeta'])
                .toMatchValues({
                    firstChunkLoaded: false,
                    sessionPlayerDataLoading: true,
                })
                .toDispatchActions(['loadRecordingMetaSuccess'])
                .toMatchValues({
                    firstChunkLoaded: false,
                    sessionPlayerDataLoading: false,
                })
            await expectLogic(logic, () => {
                logic.actions.loadRecordingSnapshots('1')
            })
                .toDispatchActions(['loadRecordingSnapshots'])
                .toMatchValues({
                    firstChunkLoaded: false,
                    sessionPlayerDataLoading: true,
                })
                .toDispatchActions(['loadRecordingSnapshotsSuccess'])
                .toMatchValues({
                    firstChunkLoaded: true,
                    sessionPlayerDataLoading: false,
                })
        })
        it('standard loading in single chunk recording', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadRecordingSnapshots('1')
            })
                .toDispatchActions(['loadRecordingSnapshots'])
                .toMatchValues({
                    firstChunkLoaded: false,
                    sessionPlayerDataLoading: true,
                })
                .toDispatchActions(['loadRecordingSnapshotsSuccess'])
                .toMatchValues({
                    firstChunkLoaded: true,
                    sessionPlayerDataLoading: false,
                })
                .toNotHaveDispatchedActions(['loadRecordingSnapshots'])
        })
        it('stays loading throughout multi chunk recording', async () => {
            await expectLogic(preflightLogic).toDispatchActions(['loadPreflightSuccess'])
            await expectLogic(logic).toMount([eventUsageLogic])

            const snapshotUrl = createSnapshotEndpoint(1)
            const firstNext = `${snapshotUrl}/?offset=200&limit=200`
            const secondNext = `${snapshotUrl}/?offset=400&limit=200`

            api.get
                .mockImplementationOnce(async (url: string) => {
                    if (combineUrl(url).pathname.match(EVENTS_SESSION_RECORDING_SNAPSHOTS_ENDPOINT_REGEX)) {
                        return { result: { ...recordingSnapshotsJson, next: firstNext } }
                    }
                })
                .mockImplementationOnce(async (url: string) => {
                    if (combineUrl(url).pathname.match(EVENTS_SESSION_RECORDING_SNAPSHOTS_ENDPOINT_REGEX)) {
                        return { result: { ...recordingSnapshotsJson, next: secondNext } }
                    }
                })
                .mockImplementationOnce(async (url: string) => {
                    if (combineUrl(url).pathname.match(EVENTS_SESSION_RECORDING_SNAPSHOTS_ENDPOINT_REGEX)) {
                        return { result: recordingSnapshotsJson }
                    }
                })

            await expectLogic(logic, () => {
                logic.actions.loadRecordingSnapshots('1')
            })
                .toDispatchActions(['loadRecordingSnapshots'])
                .toMatchValues({
                    firstChunkLoaded: false,
                    sessionPlayerDataLoading: true,
                })
                .toDispatchActions(['loadRecordingSnapshotsSuccess'])
                .toMatchValues({
                    firstChunkLoaded: true,
                    sessionPlayerDataLoading: true,
                })
                .toDispatchActions([logic.actionCreators.loadRecordingSnapshots(undefined, firstNext)])
                .toMatchValues({
                    firstChunkLoaded: true,
                    sessionPlayerDataLoading: true,
                })
                .toDispatchActions(['loadRecordingSnapshotsSuccess'])
                .toMatchValues({
                    firstChunkLoaded: true,
                    sessionPlayerDataLoading: true,
                })
                .toDispatchActions([logic.actionCreators.loadRecordingSnapshots(undefined, secondNext)])
                .toMatchValues({
                    firstChunkLoaded: true,
                    sessionPlayerDataLoading: true,
                })
                .toDispatchActions(['loadRecordingSnapshotsSuccess'])
                .toMatchValues({
                    firstChunkLoaded: true,
                    sessionPlayerDataLoading: false,
                })
        })
        describe('isPlayable', () => {
            it('first chunk loads but no full snapshot yet', async () => {
                await expectLogic(logic, () => {
                    logic.actions.loadRecordingSnapshots('1')
                })
                    .toDispatchActions(['loadRecordingSnapshots', 'loadRecordingSnapshotsSuccess'])
                    .toMatchValues({
                        sessionPlayerData: recordingSnapshotsJson,
                        firstChunkLoaded: true,
                        isPlayable: false,
                    })
            })
            it("first chunk loads and there's at least one full snapshot", async () => {
                const newSnapshots = [
                    ...recordingSnapshotsJson.snapshots,
                    {
                        type: 2,
                        data: { source: 0 },
                        timestamp: 1634019260528,
                    },
                ]
                api.get.mockImplementationOnce(async (url: string) => {
                    if (combineUrl(url).pathname.match(EVENTS_SESSION_RECORDING_SNAPSHOTS_ENDPOINT_REGEX)) {
                        return {
                            result: {
                                ...recordingSnapshotsJson,
                                snapshots: newSnapshots,
                            },
                        }
                    }
                })

                await expectLogic(logic, () => {
                    logic.actions.loadRecordingSnapshots('1')
                })
                    .toDispatchActions(['loadRecordingSnapshots', 'loadRecordingSnapshotsSuccess'])
                    .toMatchValues({
                        sessionPlayerData: { ...recordingSnapshotsJson, snapshots: newSnapshots },
                        firstChunkLoaded: true,
                        isPlayable: true,
                    })
            })
            it('session player data is still loading', async () => {
                const newSnapshots = [
                    ...recordingSnapshotsJson.snapshots,
                    {
                        type: 2,
                        data: { source: 0 },
                        timestamp: 1634019260528,
                    },
                ]
                api.get.mockImplementationOnce(async (url: string) => {
                    if (combineUrl(url).pathname.match(EVENTS_SESSION_RECORDING_SNAPSHOTS_ENDPOINT_REGEX)) {
                        return {
                            result: {
                                ...recordingSnapshotsJson,
                                snapshots: newSnapshots,
                            },
                        }
                    }
                })

                await expectLogic(logic, () => {
                    logic.actions.loadRecordingSnapshots('1')
                })
                    .toDispatchActions(['loadRecordingSnapshots'])
                    .toMatchValues({
                        firstChunkLoaded: false,
                        isPlayable: false,
                    })
                    .toDispatchActions(['loadRecordingSnapshotsSuccess'])
                    .toMatchValues({
                        sessionPlayerData: { ...recordingSnapshotsJson, snapshots: newSnapshots },
                        firstChunkLoaded: true,
                        isPlayable: true,
                    })
            })
        })
    })
})
