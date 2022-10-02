import {
    parseMetadataResponse,
    sessionRecordingDataLogic,
} from 'scenes/session-recordings/player/sessionRecordingDataLogic'
import { api, MOCK_TEAM_ID } from 'lib/api.mock'
import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import recordingSnapshotsJson from '../__mocks__/recording_snapshots.json'
import recordingMetaJson from '../__mocks__/recording_meta.json'
import recordingEventsJson from '../__mocks__/recording_events.json'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { combineUrl } from 'kea-router'
import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'

const createSnapshotEndpoint = (id: number): string => `api/projects/${MOCK_TEAM_ID}/session_recordings/${id}/snapshots`
const EVENTS_SESSION_RECORDING_SNAPSHOTS_ENDPOINT_REGEX = new RegExp(
    `api/projects/${MOCK_TEAM_ID}/session_recordings/\\d/snapshots`
)
const EVENTS_SESSION_RECORDING_META_ENDPOINT = `api/projects/${MOCK_TEAM_ID}/session_recordings`
const EVENTS_SESSION_RECORDING_EVENTS_ENDPOINT = `api/projects/${MOCK_TEAM_ID}/events`

describe('sessionRecordingDataLogic', () => {
    let logic: ReturnType<typeof sessionRecordingDataLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/session_recordings/:id/snapshots': { result: recordingSnapshotsJson },
                '/api/projects/:team/session_recordings/:id': { result: recordingMetaJson },
                '/api/projects/:team/events': { results: recordingEventsJson },
            },
        })
        initKeaTests()
        logic = sessionRecordingDataLogic({ sessionRecordingId: '2' })
        logic.mount()
    })

    describe('core assumptions', () => {
        it('mounts other logics', async () => {
            await expectLogic(logic).toMount([eventUsageLogic])
        })
        it('has default values', async () => {
            await expectLogic(logic).toMatchValues({
                sessionRecordingId: null,
                sessionPlayerData: {
                    bufferedTo: null,
                    metadata: { recordingDurationMs: 0, segments: [], startAndEndTimesByWindowId: {} },
                    next: undefined,
                    person: null,
                    snapshotsByWindowId: {},
                },
                sessionEventsData: null,
                filters: {},
                chunkPaginationIndex: 0,
                sessionEventsDataLoading: false,
            })
        })
    })

    describe('loading session core', () => {
        it('is triggered by mounting', async () => {
            const expectedData = {
                person: recordingMetaJson.person,
                metadata: parseMetadataResponse(recordingMetaJson.session_recording),
                bufferedTo: {
                    time: 44579,
                    windowId: '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f',
                },
                next: undefined,
                snapshotsByWindowId: recordingSnapshotsJson.snapshot_data_by_window_id,
            }
            await expectLogic(logic)
                .toDispatchActions(['loadEntireRecording', 'loadRecordingMetaSuccess', 'loadRecordingSnapshotsSuccess'])
                .toFinishAllListeners()
                .toMatchValues({
                    sessionPlayerData: expectedData,
                })
        })

        it('fetch metadata error and snapshots success', async () => {
            silenceKeaLoadersErrors()
            // Unmount and remount the logic to trigger fetching the data again after the mock change
            logic.unmount()
            useMocks({
                get: {
                    '/api/projects/:team/session_recordings/:id': () => [500, { status: 0 }],
                },
            })
            logic.mount()

            await expectLogic(logic)
                .toDispatchActions(['loadRecordingMeta', 'loadRecordingSnapshots', 'loadRecordingMetaFailure'])
                .toFinishAllListeners()
                .toMatchValues({
                    sessionPlayerData: {
                        bufferedTo: null,
                        metadata: { recordingDurationMs: 0, segments: [], startAndEndTimesByWindowId: {} },
                        next: undefined,
                        person: null,
                        snapshotsByWindowId: recordingSnapshotsJson.snapshot_data_by_window_id,
                    },
                })
            resumeKeaLoadersErrors()
        })
        it('fetch metadata success and snapshots error', async () => {
            silenceKeaLoadersErrors()
            // Unmount and remount the logic to trigger fetching the data again after the mock change
            logic.unmount()
            useMocks({
                get: {
                    '/api/projects/:team/session_recordings/:id/snapshots': () => [500, { status: 0 }],
                },
            })
            logic.mount()

            await expectLogic(logic)
                .toDispatchActions(['loadRecordingSnapshots', 'loadRecordingSnapshotsFailure'])
                .toMatchValues({
                    sessionPlayerData: {
                        person: recordingMetaJson.person,
                        metadata: parseMetadataResponse(recordingMetaJson.session_recording),
                        snapshotsByWindowId: {},
                        bufferedTo: null,
                    },
                })
            resumeKeaLoadersErrors()
        })
    })

    describe('loading session events', () => {
        const expectedEvents = [
            expect.objectContaining(recordingEventsJson[1]),
            expect.objectContaining(recordingEventsJson[2]),
            expect.objectContaining(recordingEventsJson[4]),
            expect.objectContaining(recordingEventsJson[5]),
            expect.objectContaining(recordingEventsJson[6]),
        ]

        it('load events after metadata with 1min buffer', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadRecordingMeta()
            })
                .toDispatchActions(['loadRecordingMeta', 'loadRecordingMetaSuccess', 'loadEvents'])
                .toMatchValues({
                    eventsApiParams: {
                        after: '2021-12-09T19:35:59Z',
                        before: '2021-12-09T20:23:24Z',
                        person_id: 1,
                        orderBy: ['timestamp'],
                    },
                })
        })
        it('no next url', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadRecordingMeta()
            })
                .toDispatchActions(['loadRecordingMeta', 'loadRecordingMetaSuccess', 'loadEvents', 'loadEventsSuccess'])
                .toNotHaveDispatchedActions(['loadEvents'])
        })
        it('fetch all events and sort by player time', async () => {
            const firstNext = `${EVENTS_SESSION_RECORDING_EVENTS_ENDPOINT}?person_id=1&before=2021-10-28T17:45:12.128000Z&after=2021-10-28T16:45:05Z`

            jest.spyOn(api, 'get')
            let count = 0
            useMocks({
                get: {
                    '/api/projects/:team/events': () => [
                        200,
                        { results: recordingEventsJson, next: count++ === 0 ? firstNext : undefined },
                    ],
                },
            })

            await expectLogic(logic, () => {
                logic.actions.loadRecordingMeta()
            })
                .toDispatchActions(['loadRecordingMeta', 'loadRecordingMetaSuccess', 'loadEvents', 'loadEventsSuccess'])
                .toMatchValues({
                    sessionEventsData: {
                        next: firstNext,
                        events: expectedEvents,
                    },
                })
                .toDispatchActions([logic.actionCreators.loadEvents(firstNext), 'loadEventsSuccess'])
                .toMatchValues({
                    sessionEventsData: {
                        next: undefined,
                        events: [
                            expect.objectContaining(recordingEventsJson[1]),
                            expect.objectContaining(recordingEventsJson[1]),
                            expect.objectContaining(recordingEventsJson[2]),
                            expect.objectContaining(recordingEventsJson[2]),
                            expect.objectContaining(recordingEventsJson[4]),
                            expect.objectContaining(recordingEventsJson[4]),
                            expect.objectContaining(recordingEventsJson[5]),
                            expect.objectContaining(recordingEventsJson[5]),
                            expect.objectContaining(recordingEventsJson[6]),
                            expect.objectContaining(recordingEventsJson[6]),
                        ],
                    },
                })
                .toNotHaveDispatchedActions(['loadEvents'])
            expect(api.get).toBeCalledTimes(3)
        })
        it('server error mid-fetch', async () => {
            const firstNext = `${EVENTS_SESSION_RECORDING_EVENTS_ENDPOINT}?person_id=1&before=2021-10-28T17:45:12.128000Z&after=2021-10-28T16:45:05Z`
            silenceKeaLoadersErrors()
            jest.spyOn(api, 'get')
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
                .mockImplementationOnce(async () => {
                    throw new Error('Error in third request')
                })
            await expectLogic(logic, () => {
                logic.actions.loadRecordingMeta()
            })
                .toDispatchActions(['loadRecordingMeta', 'loadRecordingMetaSuccess', 'loadEvents', 'loadEventsSuccess'])
                .toMatchValues({
                    sessionEventsData: {
                        next: firstNext,
                        events: expectedEvents,
                    },
                })
                .toDispatchActions([logic.actionCreators.loadEvents(firstNext), 'loadEventsFailure'])
            resumeKeaLoadersErrors()
            expect(api.get).toBeCalledTimes(3)
        })
    })

    describe('loading session snapshots', () => {
        const snapsWindow1 =
            recordingSnapshotsJson.snapshot_data_by_window_id[
                '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f'
            ]
        const snapsWindow2 =
            recordingSnapshotsJson.snapshot_data_by_window_id[
                '182830cdf4b28a9-02530f1179ed36-1c525635-384000-182830cdf4c2841'
            ]

        it('no next url', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadRecordingSnapshots()
            })
                .toDispatchActions(['loadRecordingSnapshots', 'loadRecordingSnapshotsSuccess'])
                .toMatchValues({
                    sessionPlayerData: {
                        person: recordingMetaJson.person,
                        metadata: parseMetadataResponse(recordingMetaJson.session_recording),
                        bufferedTo: {
                            time: 44579,
                            windowId: '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f',
                        },
                        next: undefined,
                        snapshotsByWindowId: recordingSnapshotsJson.snapshot_data_by_window_id,
                    },
                })
                .toNotHaveDispatchedActions(['loadRecordingSnapshots'])
        })

        it('fetch all chunks of recording', async () => {
            await expectLogic(preflightLogic).toDispatchActions(['loadPreflightSuccess'])
            await expectLogic(logic).toMount([eventUsageLogic]).toFinishAllListeners()
            jest.spyOn(api, 'get')
            api.get.mockClear()

            const snapshotUrl = createSnapshotEndpoint(1)
            const firstNext = `${snapshotUrl}/?offset=200&limit=200`

            api.get
                .mockImplementationOnce(async (url: string) => {
                    if (combineUrl(url).pathname.match(EVENTS_SESSION_RECORDING_SNAPSHOTS_ENDPOINT_REGEX)) {
                        return { result: { ...recordingSnapshotsJson, next: firstNext } }
                    }
                })
                .mockImplementationOnce(async (url: string) => {
                    if (combineUrl(url).pathname.match(EVENTS_SESSION_RECORDING_SNAPSHOTS_ENDPOINT_REGEX)) {
                        return { result: { ...recordingSnapshotsJson } }
                    }
                })

            await expectLogic(logic, () => {
                logic.actions.loadRecordingSnapshots()
            })
                .toDispatchActions(['loadRecordingSnapshots', 'loadRecordingSnapshotsSuccess'])
                .toMatchValues({
                    sessionPlayerData: {
                        person: recordingMetaJson.person,
                        metadata: parseMetadataResponse(recordingMetaJson.session_recording),
                        bufferedTo: {
                            time: 44579,
                            windowId: '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f',
                        },
                        snapshotsByWindowId: {
                            '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f': snapsWindow1,
                            '182830cdf4b28a9-02530f1179ed36-1c525635-384000-182830cdf4c2841': snapsWindow2,
                        },
                        next: firstNext,
                    },
                })
                .toDispatchActions([
                    logic.actionCreators.loadRecordingSnapshots(firstNext),
                    'loadRecordingSnapshotsSuccess',
                ])
                .toMatchValues({
                    sessionPlayerData: {
                        person: recordingMetaJson.person,
                        metadata: parseMetadataResponse(recordingMetaJson.session_recording),
                        bufferedTo: {
                            time: 44579,
                            windowId: '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f',
                        },
                        snapshotsByWindowId: {
                            '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f': [
                                ...snapsWindow1,
                                ...snapsWindow1,
                            ],
                            '182830cdf4b28a9-02530f1179ed36-1c525635-384000-182830cdf4c2841': [
                                ...snapsWindow2,
                                ...snapsWindow2,
                            ],
                        },
                        next: undefined,
                    },
                })
                .toFinishAllListeners()
            expect(api.get).toBeCalledTimes(2)
        })
        it('server error mid-way through recording', async () => {
            await expectLogic(preflightLogic).toDispatchActions(['loadPreflightSuccess'])
            await expectLogic(logic).toMount([eventUsageLogic]).toFinishAllListeners()
            jest.spyOn(api, 'get')

            api.get.mockClear()
            expect(api.get).toBeCalledTimes(0)

            const snapshotUrl = createSnapshotEndpoint(1)
            const firstNext = `${snapshotUrl}/?offset=200&limit=200`
            silenceKeaLoadersErrors()
            api.get
                .mockImplementationOnce(async (url: string) => {
                    if (combineUrl(url).pathname.match(EVENTS_SESSION_RECORDING_SNAPSHOTS_ENDPOINT_REGEX)) {
                        return { result: { ...recordingSnapshotsJson, next: firstNext } }
                    }
                })
                .mockImplementationOnce(async () => {
                    throw new Error('Error in second request')
                })

            await expectLogic(logic, async () => {
                await logic.actions.loadRecordingSnapshots()
            })
                .toDispatchActions(['loadRecordingSnapshots', 'loadRecordingSnapshotsSuccess'])
                .toMatchValues({
                    sessionPlayerData: {
                        person: recordingMetaJson.person,
                        metadata: parseMetadataResponse(recordingMetaJson.session_recording),
                        bufferedTo: {
                            time: 44579,
                            windowId: '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f',
                        },
                        snapshotsByWindowId: {
                            '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f': snapsWindow1,
                            '182830cdf4b28a9-02530f1179ed36-1c525635-384000-182830cdf4c2841': snapsWindow2,
                        },
                        next: firstNext,
                    },
                })
                .toDispatchActions([
                    logic.actionCreators.loadRecordingSnapshots(firstNext),
                    'loadRecordingSnapshotsFailure',
                ])
                .toFinishAllListeners()
            resumeKeaLoadersErrors()
            expect(api.get).toBeCalledTimes(2)
        })
    })
})
