import {
    prepareRecordingSnapshots,
    sessionRecordingDataLogic,
    convertSnapshotsByWindowId,
} from 'scenes/session-recordings/player/sessionRecordingDataLogic'
import { api, MOCK_TEAM_ID } from 'lib/api.mock'
import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import recordingSnapshotsJson from '../__mocks__/recording_snapshots.json'
import recordingMetaJson from '../__mocks__/recording_meta.json'
import recordingEventsJson from '../__mocks__/recording_events_query'
import recordingPerformanceEventsJson from '../__mocks__/recording_performance_events.json'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'
import { AvailableFeature } from '~/types'
import { useAvailableFeatures } from '~/mocks/features'

const createSnapshotEndpoint = (id: number): string => `api/projects/${MOCK_TEAM_ID}/session_recordings/${id}/snapshots`
const EVENTS_SESSION_RECORDING_SNAPSHOTS_ENDPOINT_REGEX = new RegExp(
    `api/projects/${MOCK_TEAM_ID}/session_recordings/\\d/snapshots`
)

const sortedRecordingSnapshotsJson = {
    snapshot_data_by_window_id: {},
}

Object.keys(recordingSnapshotsJson.snapshot_data_by_window_id).forEach((key) => {
    sortedRecordingSnapshotsJson.snapshot_data_by_window_id[key] = [
        ...recordingSnapshotsJson.snapshot_data_by_window_id[key],
    ].sort((a, b) => a.timestamp - b.timestamp)
})

describe('sessionRecordingDataLogic', () => {
    let logic: ReturnType<typeof sessionRecordingDataLogic.build>

    beforeEach(async () => {
        useAvailableFeatures([AvailableFeature.RECORDINGS_PERFORMANCE])
        useMocks({
            get: {
                '/api/projects/:team/session_recordings/:id/snapshots': recordingSnapshotsJson,
                '/api/projects/:team/session_recordings/:id': recordingMetaJson,
                '/api/projects/:team/performance_events': { results: recordingPerformanceEventsJson },
            },
            post: {
                '/api/projects/:team/query': recordingEventsJson,
            },
        })
        initKeaTests()
        logic = sessionRecordingDataLogic({ sessionRecordingId: '2' })
        logic.mount()
        // Most of these tests assume the metadata is being loaded upfront which is the typical case
        logic.actions.loadRecording()
        jest.spyOn(api, 'get')
        jest.spyOn(api, 'create')
    })

    describe('core assumptions', () => {
        it('mounts other logics', async () => {
            await expectLogic(logic).toMount([eventUsageLogic, teamLogic, userLogic])
        })
        it('has default values', async () => {
            expect(logic.values).toMatchObject({
                bufferedToTime: null,
                durationMs: 0,
                start: undefined,
                end: undefined,
                segments: [],
                sessionEventsData: null,
                filters: {},
                chunkPaginationIndex: 0,
                sessionEventsDataLoading: false,
            })
        })
    })

    describe('loading session core', () => {
        it('loads all data', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadRecording(true)
            })
                .toDispatchActions([
                    'loadRecording',
                    'loadRecordingMeta',
                    'loadRecordingMetaSuccess',
                    'loadRecordingSnapshots',
                    'loadRecordingSnapshotsSuccess',
                ])
                .toFinishAllListeners()

            expect(logic.values.sessionPlayerData).toMatchObject({
                person: recordingMetaJson.person,
                bufferedToTime: 11868,
                snapshotsByWindowId: sortedRecordingSnapshotsJson.snapshot_data_by_window_id,
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
            logic.actions.loadRecording()

            await expectLogic(logic)
                .toDispatchActionsInAnyOrder(['loadRecordingMeta', 'loadRecordingMetaFailure'])
                .toFinishAllListeners()
                .toMatchValues({
                    sessionPlayerData: {
                        bufferedToTime: null,
                        start: undefined,
                        end: undefined,
                        durationMs: 0,
                        pinnedCount: 0,
                        segments: [],
                        person: null,
                        snapshotsByWindowId: {},
                        fullyLoaded: false,
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
            logic.actions.loadRecording(true)

            await expectLogic(logic).toDispatchActions(['loadRecordingSnapshots', 'loadRecordingSnapshotsFailure'])
            expect(logic.values.sessionPlayerData).toMatchObject({
                person: recordingMetaJson.person,
                durationMs: 11868,
                snapshotsByWindowId: {},
                bufferedToTime: 0,
            })
            resumeKeaLoadersErrors()
        })
    })

    describe('loading session events', () => {
        beforeEach(async () => {
            // Test session events loading in isolation from other features
            useAvailableFeatures([])
            initKeaTests()
            useAvailableFeatures([])
            initKeaTests()
            logic = sessionRecordingDataLogic({ sessionRecordingId: '2' })
            logic.mount()
            logic.actions.loadRecording()
            api.get.mockClear()
            api.create.mockClear()
        })

        it('load events after metadata with 1min buffer', async () => {
            api.create
                .mockImplementationOnce(async () => {
                    return recordingEventsJson
                })
                .mockImplementationOnce(async () => {
                    // Once is the server events
                    return {
                        results: [],
                    }
                })

            await expectLogic(logic, () => {
                logic.actions.loadRecording(true)
            }).toDispatchActions(['loadRecordingMeta', 'loadRecordingMetaSuccess', 'loadEvents', 'loadEventsSuccess'])

            expect(api.create).toHaveBeenCalledWith(
                `api/projects/${MOCK_TEAM_ID}/query`,
                {
                    client_query_id: undefined,
                    query: {
                        after: '2023-05-01T14:45:20+00:00',
                        before: '2023-05-01T14:47:32+00:00',
                        kind: 'EventsQuery',
                        limit: 1000000,
                        orderBy: ['timestamp ASC'],
                        personId: 11,
                        properties: [{ key: '$session_id', operator: 'exact', type: 'event', value: ['2'] }],
                        select: [
                            'uuid',
                            'event',
                            'timestamp',
                            'elements_chain',
                            'properties.$window_id',
                            'properties.$current_url',
                            'properties.$event_type',
                        ],
                    },
                },
                expect.anything()
            )

            expect(logic.values.sessionEventsData).toHaveLength(recordingEventsJson.results.length)
        })
    })

    describe('loading session performance events', () => {
        describe("don't call performance endpoint", () => {
            beforeEach(async () => {
                useAvailableFeatures([])
                initKeaTests()
                logic = sessionRecordingDataLogic({ sessionRecordingId: '2' })
                logic.mount()
                logic.actions.loadRecording()
                api.get.mockClear()
            })

            it("user doesn't have the performance feature", async () => {
                api.get.mockClear()
                await expectLogic(logic, async () => {
                    logic.actions.loadRecording(true)
                })
                    .toDispatchActions(['loadRecordingMeta', 'loadRecordingMetaSuccess'])
                    .toDispatchActionsInAnyOrder([
                        'loadEvents',
                        'loadEventsSuccess',
                        'loadPerformanceEvents',
                        'loadPerformanceEventsSuccess',
                    ])
                    .toMatchValues({
                        performanceEvents: [],
                    })

                // data, meta... but not performance events
                expect(api.get).toBeCalledTimes(2)
            })
        })

        it('load performance events', async () => {
            logic = sessionRecordingDataLogic({ sessionRecordingId: '2' })
            logic.mount()
            logic.actions.loadRecording(true)

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
                    performanceEvents: expect.arrayContaining([
                        expect.objectContaining({
                            entry_type: 'navigation',
                        }),
                    ]),
                })
        })
    })

    describe('loading session snapshots', () => {
        it('no next url', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadRecordingSnapshots()
            })
                .toDispatchActions(['loadRecordingSnapshots', 'loadRecordingSnapshotsSuccess'])
                .toNotHaveDispatchedActions(['loadRecordingSnapshots'])
                .toFinishAllListeners()

            expect(logic.values).toMatchObject({
                sessionPlayerData: {
                    person: recordingMetaJson.person,
                    bufferedToTime: 11868,
                    durationMs: 11868,
                    snapshotsByWindowId: sortedRecordingSnapshotsJson.snapshot_data_by_window_id,
                },
                sessionPlayerSnapshotData: {
                    next: null,
                },
            })
        })

        it('fetch all chunks of recording', async () => {
            const snapshots1 = { snapshot_data_by_window_id: {} }
            const snapshots2 = { snapshot_data_by_window_id: {} }

            Object.keys(sortedRecordingSnapshotsJson.snapshot_data_by_window_id).forEach((windowId) => {
                snapshots1.snapshot_data_by_window_id[windowId] =
                    sortedRecordingSnapshotsJson.snapshot_data_by_window_id[windowId].slice(0, 3)
                snapshots2.snapshot_data_by_window_id[windowId] =
                    sortedRecordingSnapshotsJson.snapshot_data_by_window_id[windowId].slice(3)
            })

            const snapshotUrl = createSnapshotEndpoint(3)
            const firstNext = `${snapshotUrl}/?offset=200&limit=200`
            let nthSnapshotCall = 0
            logic.unmount()
            useAvailableFeatures([])
            useMocks({
                get: {
                    '/api/projects/:team/session_recordings/:id/snapshots': (req) => {
                        if (req.url.pathname.match(EVENTS_SESSION_RECORDING_SNAPSHOTS_ENDPOINT_REGEX)) {
                            const payload = {
                                ...(nthSnapshotCall === 0 ? snapshots1 : snapshots2),
                                next: nthSnapshotCall === 0 ? firstNext : undefined,
                            }
                            nthSnapshotCall += 1
                            return [200, payload]
                        }
                    },
                },
            })

            logic.mount()
            logic.actions.loadRecording(true)

            await expectLogic(preflightLogic).toDispatchActions(['loadPreflightSuccess'])
            api.get.mockClear()
            await expectLogic(logic).toMount([eventUsageLogic]).toFinishAllListeners()
            await expectLogic(logic).toDispatchActions(['loadRecordingSnapshots', 'loadRecordingSnapshotsSuccess'])

            await expectLogic(logic)
                .toDispatchActions([
                    logic.actionCreators.loadRecordingSnapshots(firstNext),
                    'loadRecordingSnapshotsSuccess',
                ])
                .toFinishAllListeners()

            expect(logic.values).toMatchObject({
                sessionPlayerData: {
                    person: recordingMetaJson.person,
                    bufferedToTime: 11868,
                    durationMs: 11868,
                },
                sessionPlayerSnapshotData: {
                    next: undefined,
                },
            })
            expect(api.get).toBeCalledTimes(3) // 2 calls to loadRecordingSnapshots + 1 call to loadPerformanceEvents
        })

        it('server error mid-way through recording', async () => {
            let nthSnapshotCall = 0
            logic.unmount()
            useAvailableFeatures([])
            useMocks({
                get: {
                    '/api/projects/:team/session_recordings/:id/snapshots': (req) => {
                        if (req.url.pathname.match(EVENTS_SESSION_RECORDING_SNAPSHOTS_ENDPOINT_REGEX)) {
                            if (nthSnapshotCall === 0) {
                                const payload = {
                                    ...recordingSnapshotsJson,
                                    next: firstNext,
                                }
                                nthSnapshotCall += 1
                                return [200, payload]
                            } else {
                                throw new Error('Error in second request')
                            }
                        }
                    },
                },
            })
            logic.mount()
            logic.actions.loadRecording()

            await expectLogic(preflightLogic).toDispatchActions(['loadPreflightSuccess'])
            await expectLogic(logic).toMount([eventUsageLogic]).toFinishAllListeners()
            api.get.mockClear()

            const snapshotUrl = createSnapshotEndpoint(1)
            const firstNext = `${snapshotUrl}/?offset=200&limit=200`
            silenceKeaLoadersErrors()

            await expectLogic(logic, () => {
                logic.actions.loadRecordingSnapshots()
            }).toDispatchActions(['loadRecordingSnapshots', 'loadRecordingSnapshotsSuccess'])

            expect(logic.values).toMatchObject({
                sessionPlayerData: {
                    person: recordingMetaJson.person,
                    bufferedToTime: 11868,
                    snapshotsByWindowId: sortedRecordingSnapshotsJson.snapshot_data_by_window_id,
                },
                sessionPlayerSnapshotData: {
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
                logic.actions.loadRecording(true)
            })
                .toDispatchActions(['loadRecording'])
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
                .toDispatchActions([eventUsageLogic.actionTypes.reportRecording]) // only dispatch once
                .toNotHaveDispatchedActions([
                    eventUsageLogic.actionTypes.reportRecording,
                    eventUsageLogic.actionTypes.reportRecording,
                ])
        })
        it('send `recording viewed` and `recording analyzed` event on first contentful paint', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadRecording(true)
            })
                .toDispatchActions(['loadRecording', 'loadRecordingSnapshotsSuccess'])
                .toDispatchActionsInAnyOrder([
                    eventUsageLogic.actionTypes.reportRecording, // loaded
                    eventUsageLogic.actionTypes.reportRecording, // viewed
                    eventUsageLogic.actionTypes.reportRecording, // analyzed
                ])
                .toMatchValues({
                    chunkPaginationIndex: 1,
                })
        })
    })

    describe('prepareRecordingSnapshots', () => {
        it('should remove duplicate snapshots and sort by timestamp', () => {
            const snapshots = convertSnapshotsByWindowId(recordingSnapshotsJson.snapshot_data_by_window_id)
            const snapshotsWithDuplicates = snapshots
                .slice(0, 2)
                .concat(snapshots.slice(0, 2))
                .concat(snapshots.slice(2))

            expect(snapshotsWithDuplicates.length).toEqual(snapshots.length + 2)

            expect(prepareRecordingSnapshots(snapshots)).toEqual(prepareRecordingSnapshots(snapshotsWithDuplicates))
        })

        it('should match snapshot', () => {
            const snapshots = convertSnapshotsByWindowId(recordingSnapshotsJson.snapshot_data_by_window_id)

            expect(prepareRecordingSnapshots(snapshots)).toMatchSnapshot()
        })
    })
})
