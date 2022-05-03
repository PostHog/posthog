import { parseMetadataResponse, sessionRecordingLogic } from 'scenes/session-recordings/sessionRecordingLogic'
import { api, MOCK_TEAM_ID } from 'lib/api.mock'
import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { eventUsageLogic, RecordingWatchedSource } from 'lib/utils/eventUsageLogic'
import recordingSnapshotsJson from './__mocks__/recording_snapshots.json'
import recordingMetaJson from './__mocks__/recording_meta.json'
import recordingEventsJson from './__mocks__/recording_events.json'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { combineUrl, router } from 'kea-router'
import { RecordingEventType } from '~/types'
import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'

const createSnapshotEndpoint = (id: number): string => `api/projects/${MOCK_TEAM_ID}/session_recordings/${id}/snapshots`
const EVENTS_SESSION_RECORDING_SNAPSHOTS_ENDPOINT_REGEX = new RegExp(
    `api/projects/${MOCK_TEAM_ID}/session_recordings/\\d/snapshots`
)
const EVENTS_SESSION_RECORDING_META_ENDPOINT = `api/projects/${MOCK_TEAM_ID}/session_recordings`
const EVENTS_SESSION_RECORDING_EVENTS_ENDPOINT = `api/projects/${MOCK_TEAM_ID}/events`

describe('sessionRecordingLogic', () => {
    let logic: ReturnType<typeof sessionRecordingLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/session_recordings/:id/snapshots': { result: recordingSnapshotsJson },
                '/api/projects/:team/session_recordings/:id': { result: recordingMetaJson },
                '/api/projects/:team/events': { results: recordingEventsJson },
            },
        })
        initKeaTests()
        logic = sessionRecordingLogic()
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
                source: RecordingWatchedSource.Unknown,
            })
        })
        it('reads recording ids from the url', async () => {
            router.actions.push(
                '/recordings',
                {},
                {
                    sessionRecordingId: '1',
                }
            )

            await expectLogic(logic).toDispatchActions([
                logic.actionCreators.loadRecordingMeta('1'),
                logic.actionCreators.loadRecordingSnapshots('1'),
            ])
        })
    })

    describe('loading session core', () => {
        it('fetch metadata and then snapshots', async () => {
            const resultAfterMetadataResponse = {
                person: recordingMetaJson.person,
                metadata: parseMetadataResponse(recordingMetaJson.session_recording),
                snapshotsByWindowId: {},
                bufferedTo: null,
            }

            await expectLogic(logic, () => {
                logic.actions.loadRecordingMeta('1')
            })
                .toDispatchActions(['loadRecordingMeta', 'loadRecordingMetaSuccess'])
                .toMatchValues({
                    sessionPlayerData: resultAfterMetadataResponse,
                })
                .toFinishAllListeners()

            const resultAfterSnapshotResponse = {
                ...resultAfterMetadataResponse,
                bufferedTo: {
                    time: 44579,
                    windowId: '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f',
                },
                next: undefined,
                snapshotsByWindowId: recordingSnapshotsJson.snapshot_data_by_window_id,
            }

            await expectLogic(logic, () => {
                logic.actions.loadRecordingSnapshots('1')
            })
                .toDispatchActions(['loadRecordingSnapshots', 'loadRecordingSnapshotsSuccess'])
                .toMatchValues({
                    sessionPlayerData: resultAfterSnapshotResponse,
                })
        })
        it('fetch snapshots and then metadata', async () => {
            const resultAfterSnapshotResponse = {
                bufferedTo: null,
                metadata: { recordingDurationMs: 0, segments: [], startAndEndTimesByWindowId: {} },
                next: undefined,
                person: null,
                snapshotsByWindowId: recordingSnapshotsJson.snapshot_data_by_window_id,
            }

            await expectLogic(logic, () => {
                logic.actions.loadRecordingSnapshots('1')
            })
                .toDispatchActions(['loadRecordingSnapshots', 'loadRecordingSnapshotsSuccess'])
                .toMatchValues({
                    sessionPlayerData: resultAfterSnapshotResponse,
                })

            const resultAfterMetadataResponse = {
                ...resultAfterSnapshotResponse,
                bufferedTo: {
                    time: 44579,
                    windowId: '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f',
                },
                person: recordingMetaJson.person,
                metadata: parseMetadataResponse(recordingMetaJson.session_recording),
            }

            await expectLogic(logic, () => {
                logic.actions.loadRecordingMeta('1')
            })
                .toDispatchActions(['loadRecordingMeta', 'loadRecordingMetaSuccess'])
                .toMatchValues({
                    sessionPlayerData: resultAfterMetadataResponse,
                })
                .toFinishAllListeners()
        })
        it('fetch metadata error and snapshots success', async () => {
            useMocks({
                get: {
                    '/api/projects/:team/session_recordings/:id': () => [500, { status: 0 }],
                },
            })

            silenceKeaLoadersErrors()
            await expectLogic(logic, () => {
                logic.actions.loadRecordingMeta('1')
            })
                .toDispatchActions(['loadRecordingMeta', 'loadRecordingMetaFailure'])
                .toMatchValues({
                    sessionPlayerData: {
                        bufferedTo: null,
                        metadata: { recordingDurationMs: 0, segments: [], startAndEndTimesByWindowId: {} },
                        next: undefined,
                        person: null,
                        snapshotsByWindowId: {},
                    },
                })
                .toFinishAllListeners()
            resumeKeaLoadersErrors()
            await expectLogic(logic, () => {
                logic.actions.loadRecordingSnapshots('1')
            })
                .toDispatchActions(['loadRecordingSnapshots', 'loadRecordingSnapshotsSuccess'])
                .toMatchValues({
                    sessionPlayerData: {
                        bufferedTo: null,
                        metadata: { recordingDurationMs: 0, segments: [], startAndEndTimesByWindowId: {} },
                        next: undefined,
                        person: null,
                        snapshotsByWindowId: recordingSnapshotsJson.snapshot_data_by_window_id,
                    },
                })
        })
        it('fetch metadata success and snapshots error', async () => {
            const expected = {
                person: recordingMetaJson.person,
                metadata: parseMetadataResponse(recordingMetaJson.session_recording),
                snapshotsByWindowId: {},
                bufferedTo: null,
            }
            silenceKeaLoadersErrors()
            useMocks({
                get: {
                    '/api/projects/:team/session_recordings/:id/snapshots': () => [500, { status: 0 }],
                },
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
            resumeKeaLoadersErrors()
        })
    })

    describe('loading session events', () => {
        const events = recordingEventsJson

        const expected_events: RecordingEventType[] = []
        expected_events.push({
            ...events[1],
            playerTime: 0,
            playerPosition: {
                time: 0,
                windowId: events[1].properties.$window_id as string,
            },
            percentageOfRecordingDuration: 0,
            isOutOfBandEvent: false,
        })

        expected_events.push({
            ...events[2],
            playerTime: 38998,
            playerPosition: {
                time: 39000,
                windowId: events[2].properties.$window_id as string,
            },
            percentageOfRecordingDuration: 1.4308651234056042,
            isOutOfBandEvent: false,
        })

        expected_events.push({
            ...events[4],
            playerTime: 39998,
            playerPosition: {
                time: 40000,
                windowId: events[2].properties.$window_id as string,
            },
            percentageOfRecordingDuration: 1.46755585429964,
            isOutOfBandEvent: true,
        })

        it('load events after metadata with 1min buffer', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadRecordingMeta('1')
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
                logic.actions.loadRecordingMeta('1')
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
                logic.actions.loadRecordingMeta('1')
            })
                .toDispatchActions(['loadRecordingMeta', 'loadRecordingMetaSuccess', 'loadEvents', 'loadEventsSuccess'])
                .toMatchValues({
                    sessionEventsData: {
                        next: firstNext,
                        events: expected_events,
                    },
                })
                .toDispatchActions([logic.actionCreators.loadEvents(firstNext), 'loadEventsSuccess'])
                .toMatchValues({
                    sessionEventsData: {
                        next: undefined,
                        events: [
                            expected_events[0],
                            expected_events[0],
                            expected_events[1],
                            expected_events[1],
                            expected_events[2],
                            expected_events[2],
                        ],
                    },
                })
                .toNotHaveDispatchedActions(['loadEvents'])
            expect(api.get).toBeCalledTimes(3)
        })
        it('server error mid-fetch', async () => {
            const firstNext = `${EVENTS_SESSION_RECORDING_EVENTS_ENDPOINT}?person_id=1&before=2021-10-28T17:45:12.128000Z&after=2021-10-28T16:45:05Z`
            silenceKeaLoadersErrors()
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
                logic.actions.loadRecordingMeta('1')
            })
                .toDispatchActions(['loadRecordingMeta', 'loadRecordingMetaSuccess', 'loadEvents', 'loadEventsSuccess'])
                .toMatchValues({
                    sessionEventsData: {
                        next: firstNext,
                        events: expected_events,
                    },
                })
                .toDispatchActions([logic.actionCreators.loadEvents(firstNext), 'loadEventsFailure'])
            resumeKeaLoadersErrors()
            expect(api.get).toBeCalledTimes(3)
        })
        it('makes the events searchable', async () => {
            api.get.mockClear()
            api.get
                .mockImplementationOnce(async (url: string) => {
                    if (combineUrl(url).pathname.startsWith(EVENTS_SESSION_RECORDING_META_ENDPOINT)) {
                        return { result: recordingMetaJson }
                    }
                })
                .mockImplementationOnce(async (url: string) => {
                    if (combineUrl(url).pathname.startsWith(EVENTS_SESSION_RECORDING_EVENTS_ENDPOINT)) {
                        return { results: recordingEventsJson, next: undefined }
                    }
                })

            await expectLogic(logic, () => {
                logic.actions.loadRecordingMeta('1')
            })
                .toDispatchActions(['loadRecordingMeta', 'loadRecordingMetaSuccess', 'loadEvents', 'loadEventsSuccess'])
                .toMatchValues({
                    eventsToShow: expected_events,
                })

            expectLogic(logic, () => {
                logic.actions.setFilters({ query: 'blah' })
            }).toMatchValues({
                filters: { query: 'blah' },
                eventsToShow: [{ ...expected_events[1], queryValue: 'blah blah' }],
            })
        })
    })

    describe('loading session snapshots', () => {
        const snaps =
            recordingSnapshotsJson.snapshot_data_by_window_id[
                '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f'
            ]

        it('no next url', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadRecordingSnapshots('1')
            })
                .toDispatchActions(['loadRecordingSnapshots', 'loadRecordingSnapshotsSuccess'])
                .toMatchValues({
                    sessionPlayerData: {
                        bufferedTo: null,
                        metadata: { recordingDurationMs: 0, segments: [], startAndEndTimesByWindowId: {} },
                        next: undefined,
                        person: null,
                        snapshotsByWindowId: recordingSnapshotsJson.snapshot_data_by_window_id,
                    },
                })
                .toNotHaveDispatchedActions(['loadRecordingSnapshots'])
        })

        it('fetch all chunks of recording', async () => {
            await expectLogic(preflightLogic).toDispatchActions(['loadPreflightSuccess'])
            await expectLogic(logic).toMount([eventUsageLogic])
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
                logic.actions.loadRecordingSnapshots('1')
            })
                .toDispatchActions(['loadRecordingSnapshots', 'loadRecordingSnapshotsSuccess'])
                .toMatchValues({
                    sessionPlayerData: {
                        bufferedTo: null,
                        metadata: { recordingDurationMs: 0, segments: [], startAndEndTimesByWindowId: {} },
                        snapshotsByWindowId: { '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f': snaps },
                        next: firstNext,
                        person: null,
                    },
                })
                .toDispatchActions([
                    logic.actionCreators.loadRecordingSnapshots(undefined, firstNext),
                    'loadRecordingSnapshotsSuccess',
                ])
                .toMatchValues({
                    sessionPlayerData: {
                        bufferedTo: null,
                        metadata: { recordingDurationMs: 0, segments: [], startAndEndTimesByWindowId: {} },
                        snapshotsByWindowId: {
                            '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f': [...snaps, ...snaps],
                        },
                        next: undefined,
                        person: null,
                    },
                })

            expect(api.get).toBeCalledTimes(2)
        })
        it('server error mid-way through recording', async () => {
            await expectLogic(preflightLogic).toDispatchActions(['loadPreflightSuccess'])
            await expectLogic(logic).toMount([eventUsageLogic])
            api.get.mockClear()

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

            await expectLogic(logic, () => {
                logic.actions.loadRecordingSnapshots('1')
            })
                .toDispatchActions(['loadRecordingSnapshots', 'loadRecordingSnapshotsSuccess'])
                .toMatchValues({
                    sessionPlayerData: {
                        bufferedTo: null,
                        metadata: { recordingDurationMs: 0, segments: [], startAndEndTimesByWindowId: {} },
                        snapshotsByWindowId: { '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f': snaps },
                        next: firstNext,
                        person: null,
                    },
                })
                .toDispatchActions([
                    logic.actionCreators.loadRecordingSnapshots(undefined, firstNext),
                    'loadRecordingSnapshotsFailure',
                ])
            resumeKeaLoadersErrors()
            expect(api.get).toBeCalledTimes(2)
        })
    })

    describe('console logs', () => {
        it('should load and parse console logs from the snapshot', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadRecordingSnapshots('1')
                logic.actions.loadRecordingMeta('1')
            })
                .toDispatchActionsInAnyOrder([
                    'loadRecordingSnapshots',
                    'loadRecordingSnapshotsSuccess',
                    'loadRecordingMeta',
                    'loadRecordingMetaSuccess',
                ])
                .toMatchValues({
                    orderedConsoleLogs: [
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
