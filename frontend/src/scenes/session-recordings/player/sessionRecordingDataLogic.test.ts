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
import recordingPerformanceEventsJson from '../__mocks__/recording_performance_events.json'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { combineUrl } from 'kea-router'
import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { teamLogic } from 'scenes/teamLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { AvailableFeature, SessionRecordingUsageType } from '~/types'
import { useAvailableFeatures } from '~/mocks/features'

const createSnapshotEndpoint = (id: number): string => `api/projects/${MOCK_TEAM_ID}/session_recordings/${id}/snapshots`
const EVENTS_SESSION_RECORDING_SNAPSHOTS_ENDPOINT_REGEX = new RegExp(
    `api/projects/${MOCK_TEAM_ID}/session_recordings/\\d/snapshots`
)
const EVENTS_SESSION_RECORDING_META_ENDPOINT = `api/projects/${MOCK_TEAM_ID}/session_recordings`
const EVENTS_SESSION_RECORDING_EVENTS_ENDPOINT = `api/projects/${MOCK_TEAM_ID}/events`

describe('sessionRecordingDataLogic', () => {
    let logic: ReturnType<typeof sessionRecordingDataLogic.build>

    beforeEach(async () => {
        useAvailableFeatures([AvailableFeature.RECORDINGS_PERFORMANCE])
        useMocks({
            get: {
                '/api/projects/:team/session_recordings/:id/snapshots': recordingSnapshotsJson,
                '/api/projects/:team/session_recordings/:id': recordingMetaJson,
                '/api/projects/:team/events': { results: recordingEventsJson },
                '/api/projects/:team/performance_events': { results: recordingPerformanceEventsJson },
            },
        })
        initKeaTests()
        logic = sessionRecordingDataLogic({ sessionRecordingId: '2' })
        logic.mount()
        await expectLogic(logic).toMount([featureFlagLogic])
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.RECORDINGS_INSPECTOR_PERFORMANCE], {
            [FEATURE_FLAGS.RECORDINGS_INSPECTOR_PERFORMANCE]: true,
        })
        jest.spyOn(api, 'get')
    })

    describe('core assumptions', () => {
        it('mounts other logics', async () => {
            await expectLogic(logic).toMount([eventUsageLogic, teamLogic, featureFlagLogic, userLogic])
        })
        it('has default values', async () => {
            await expectLogic(logic).toMatchValues({
                sessionRecordingId: null,
                sessionPlayerData: {
                    bufferedTo: null,
                    metadata: { recordingDurationMs: 0, segments: [], playlists: [], startAndEndTimesByWindowId: {} },
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
                metadata: parseMetadataResponse(recordingMetaJson),
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

        it('fetch metadata error', async () => {
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
                .toDispatchActionsInAnyOrder(['loadRecordingMeta', 'loadRecordingMetaFailure'])
                .toFinishAllListeners()
                .toMatchValues({
                    sessionPlayerData: {
                        bufferedTo: null,
                        metadata: {
                            recordingDurationMs: 0,
                            segments: [],
                            playlists: [],
                            startAndEndTimesByWindowId: {},
                        },
                        next: undefined,
                        person: null,
                        snapshotsByWindowId: {},
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
                        metadata: parseMetadataResponse(recordingMetaJson),
                        snapshotsByWindowId: {},
                        bufferedTo: null,
                    },
                })
            resumeKeaLoadersErrors()
        })
    })

    describe('loading session events', () => {
        const expectedEvents = [
            expect.objectContaining(recordingEventsJson[0]),
            expect.objectContaining(recordingEventsJson[1]),
            expect.objectContaining(recordingEventsJson[2]),
            expect.objectContaining(recordingEventsJson[4]),
            expect.objectContaining(recordingEventsJson[5]),
            expect.objectContaining(recordingEventsJson[6]),
        ]

        beforeEach(async () => {
            // Test session events loading in isolation from other features
            useAvailableFeatures([])
            initKeaTests()
            useAvailableFeatures([])
            initKeaTests()
            logic = sessionRecordingDataLogic({ sessionRecordingId: '2' })
            logic.mount()
            api.get.mockClear()
        })

        it('load events after metadata with 1min buffer', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadRecordingMeta()
            })
                .toDispatchActions(['loadRecordingMeta', 'loadRecordingMetaSuccess', 'loadEvents'])
                .toMatchValues({
                    eventsApiParams: {
                        after: '2021-12-09T19:35:59Z',
                        before: '2021-12-09T20:23:24Z',
                        person_id: '1',
                        orderBy: ['timestamp'],
                        properties: {
                            type: 'OR',
                            values: [
                                {
                                    type: 'AND',
                                    values: [
                                        {
                                            key: '$session_id',
                                            operator: 'is_not_set',
                                            type: 'event',
                                            value: 'is_not_set',
                                        },
                                    ],
                                },
                                {
                                    type: 'AND',
                                    values: [
                                        {
                                            key: '$session_id',
                                            operator: 'exact',
                                            type: 'event',
                                            value: ['2'],
                                        },
                                    ],
                                },
                            ],
                        },
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
                .toNotHaveDispatchedActions(['loadEvents'])

            expect(logic.values.sessionEventsData).toMatchObject({
                next: undefined,
                events: [
                    expect.objectContaining(recordingEventsJson[0]),
                    expect.objectContaining(recordingEventsJson[1]),
                    expect.objectContaining(recordingEventsJson[0]),
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
            })

            // data, meta, events, and then first next events
            expect(api.get).toBeCalledTimes(4)
        })
        it('server error mid-fetch', async () => {
            const firstNext = `${EVENTS_SESSION_RECORDING_EVENTS_ENDPOINT}?person_id=1&before=2021-10-28T17:45:12.128000Z&after=2021-10-28T16:45:05Z`
            silenceKeaLoadersErrors()
            api.get
                .mockImplementationOnce(async (url: string) => {
                    if (combineUrl(url).pathname.startsWith(EVENTS_SESSION_RECORDING_META_ENDPOINT)) {
                        return recordingMetaJson
                    }
                })
                .mockImplementationOnce(async (url: string) => {
                    if (combineUrl(url).pathname.match(EVENTS_SESSION_RECORDING_SNAPSHOTS_ENDPOINT_REGEX)) {
                        return { ...recordingSnapshotsJson }
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

            // data, meta, events, and then errored out on first next events
            expect(api.get).toBeCalledTimes(4)
        })
    })

    describe('loading session performance events', () => {
        describe("don't call performance endpoint", () => {
            beforeEach(async () => {
                useAvailableFeatures([])
                initKeaTests()
                logic = sessionRecordingDataLogic({ sessionRecordingId: '2' })
                logic.mount()
                await expectLogic(logic).toMount(featureFlagLogic)
                featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.RECORDINGS_INSPECTOR_PERFORMANCE], {
                    [FEATURE_FLAGS.RECORDINGS_INSPECTOR_PERFORMANCE]: false,
                })
                api.get.mockClear()
            })

            it('if ff is off', async () => {
                await expectLogic(logic, () => {
                    logic.actions.loadRecordingMeta()
                })
                    .toDispatchActions(['loadRecordingMeta', 'loadRecordingMetaSuccess'])
                    .toDispatchActionsInAnyOrder([
                        'loadEvents',
                        'loadEventsSuccess',
                        'loadPerformanceEvents',
                        'loadPerformanceEventsSuccess',
                    ])
                    .toMatchValues({
                        performanceEvents: null,
                    })

                // data, meta, events... but not performance events
                expect(api.get).toBeCalledTimes(3)
            })

            it("if ff is on but user doesn't have the performance feature", async () => {
                api.get.mockClear()
                await expectLogic(logic, async () => {
                    featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.RECORDINGS_INSPECTOR_PERFORMANCE], {
                        [FEATURE_FLAGS.RECORDINGS_INSPECTOR_PERFORMANCE]: true,
                    })
                    logic.actions.loadRecordingMeta()
                })
                    .toDispatchActions(['loadRecordingMeta', 'loadRecordingMetaSuccess'])
                    .toDispatchActionsInAnyOrder([
                        'loadEvents',
                        'loadEventsSuccess',
                        'loadPerformanceEvents',
                        'loadPerformanceEventsSuccess',
                    ])
                    .toMatchValues({
                        performanceEvents: null,
                    })

                // data, meta, events... but not performance events
                expect(api.get).toBeCalledTimes(3)
            })
        })

        it('load performance events', async () => {
            logic = sessionRecordingDataLogic({ sessionRecordingId: '2' })
            logic.mount()
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.RECORDINGS_INSPECTOR_PERFORMANCE], {
                [FEATURE_FLAGS.RECORDINGS_INSPECTOR_PERFORMANCE]: true,
            })

            await expectLogic(logic, () => {
                logic.actions.loadRecordingMeta()
            })
                .toDispatchActions([
                    'loadRecordingMeta',
                    'loadRecordingMetaSuccess',
                    'loadPerformanceEvents',
                    'loadPerformanceEventsSuccess',
                ])
                .toMatchValues({
                    eventsApiParams: {
                        after: '2021-12-09T19:35:59Z',
                        before: '2021-12-09T20:23:24Z',
                        person_id: '1',
                        orderBy: ['timestamp'],
                        properties: {
                            type: 'OR',
                            values: [
                                {
                                    type: 'AND',
                                    values: [
                                        {
                                            key: '$session_id',
                                            operator: 'is_not_set',
                                            type: 'event',
                                            value: 'is_not_set',
                                        },
                                    ],
                                },
                                {
                                    type: 'AND',
                                    values: [
                                        {
                                            key: '$session_id',
                                            operator: 'exact',
                                            type: 'event',
                                            value: ['2'],
                                        },
                                    ],
                                },
                            ],
                        },
                    },
                    performanceEvents: recordingPerformanceEventsJson,
                })
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
                        metadata: parseMetadataResponse(recordingMetaJson),
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
            api.get.mockClear()

            const snapshotUrl = createSnapshotEndpoint(1)
            const firstNext = `${snapshotUrl}/?offset=200&limit=200`

            api.get
                .mockImplementationOnce(async (url: string) => {
                    if (combineUrl(url).pathname.match(EVENTS_SESSION_RECORDING_SNAPSHOTS_ENDPOINT_REGEX)) {
                        return { ...recordingSnapshotsJson, next: firstNext }
                    }
                })
                .mockImplementationOnce(async (url: string) => {
                    if (combineUrl(url).pathname.match(EVENTS_SESSION_RECORDING_SNAPSHOTS_ENDPOINT_REGEX)) {
                        return { ...recordingSnapshotsJson }
                    }
                })

            await expectLogic(logic, () => {
                logic.actions.loadRecordingSnapshots()
            }).toDispatchActions(['loadRecordingSnapshots', 'loadRecordingSnapshotsSuccess'])

            expectLogic(logic).toMatchValues({
                sessionPlayerData: {
                    person: recordingMetaJson.person,
                    metadata: parseMetadataResponse(recordingMetaJson),
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
            await expectLogic(logic)
                .toDispatchActions([
                    logic.actionCreators.loadRecordingSnapshots(firstNext),
                    'loadRecordingSnapshotsSuccess',
                ])
                .toMatchValues({
                    sessionPlayerData: {
                        person: recordingMetaJson.person,
                        metadata: parseMetadataResponse(recordingMetaJson),
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

            api.get.mockClear()
            expect(api.get).toBeCalledTimes(0)

            const snapshotUrl = createSnapshotEndpoint(1)
            const firstNext = `${snapshotUrl}/?offset=200&limit=200`
            silenceKeaLoadersErrors()
            api.get
                .mockImplementationOnce(async (url: string) => {
                    if (combineUrl(url).pathname.match(EVENTS_SESSION_RECORDING_SNAPSHOTS_ENDPOINT_REGEX)) {
                        return { ...recordingSnapshotsJson, next: firstNext }
                    }
                })
                .mockImplementationOnce(async () => {
                    throw new Error('Error in second request')
                })

            await expectLogic(logic, async () => {
                await logic.actions.loadRecordingSnapshots()
            }).toDispatchActions(['loadRecordingSnapshots', 'loadRecordingSnapshotsSuccess'])

            expectLogic(logic).toMatchValues({
                sessionPlayerData: {
                    person: recordingMetaJson.person,
                    metadata: parseMetadataResponse(recordingMetaJson),
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
            await expectLogic(logic)
                .toDispatchActions([
                    logic.actionCreators.loadRecordingSnapshots(firstNext),
                    'loadRecordingSnapshotsFailure',
                ])
                .toFinishAllListeners()
            resumeKeaLoadersErrors()
            expect(api.get).toBeCalledTimes(2)
        })
    })

    describe('report usage', () => {
        it('send `recording loaded` event only when entire recording has loaded', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadEntireRecording()
            })
                .toDispatchActions(['loadEntireRecording'])
                .toDispatchActionsInAnyOrder([
                    'loadRecordingMeta',
                    'loadRecordingMetaSuccess',
                    'loadRecordingSnapshots',
                    'loadRecordingSnapshotsSuccess',
                    'loadEvents',
                    'loadEventsSuccess',
                    'loadPerformanceEvents',
                    'loadPerformanceEventsSuccess',
                ])
                .toDispatchActions([logic.actionCreators.reportUsage(SessionRecordingUsageType.LOADED)]) // only dispatch once
                .toNotHaveDispatchedActions([logic.actionCreators.reportUsage(SessionRecordingUsageType.LOADED)])
        })
        it('send `recording viewed` and `recording analyzed` event on first contentful paint', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadEntireRecording()
            })
                .toDispatchActions([
                    'loadEntireRecording',
                    'loadRecordingSnapshotsSuccess',
                    eventUsageLogic.actionTypes.reportRecording,
                    eventUsageLogic.actionTypes.reportRecording,
                ])
                .toMatchValues({
                    chunkPaginationIndex: 1,
                })
        })
    })
})
