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
                '/api/projects/:team/session_recordings/:id/snapshots': (req) => {
                    if (req.params.id === 'forced_upgrade') {
                        // the API will 302 to the version 2 endpoint, which (in production) fetch auto-follows
                        return [
                            200,
                            {
                                sources: [
                                    {
                                        source: 'blob',
                                        start_timestamp: '2023-08-11T12:03:36.097000Z',
                                        end_timestamp: '2023-08-11T12:04:52.268000Z',
                                        blob_key: '1691755416097-1691755492268',
                                    },
                                ],
                            },
                        ]
                    }
                    return [200, recordingSnapshotsJson]
                },
                '/api/projects/:team/session_recordings/:id': recordingMetaJson,
            },
            post: {
                '/api/projects/:team/query': recordingEventsJson,
            },
        })
        initKeaTests()
        logic = sessionRecordingDataLogic({ sessionRecordingId: '2' })
        logic.mount()
        // Most of these tests assume the metadata is being loaded upfront which is the typical case
        logic.actions.loadRecordingMeta()
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
                logic.actions.loadRecordingMeta()
                logic.actions.loadRecordingSnapshots()
            })
                .toDispatchActions(['loadRecordingMetaSuccess', 'loadRecordingSnapshotsSuccess'])
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
            logic.actions.loadRecordingMeta()

            await expectLogic(logic)
                .toDispatchActionsInAnyOrder(['loadRecordingMetaFailure'])
                .toFinishAllListeners()
                .toMatchValues({
                    sessionPlayerData: {
                        bufferedToTime: null,
                        start: undefined,
                        end: undefined,
                        durationMs: 0,
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
            logic.actions.loadRecordingMeta()
            logic.actions.loadRecordingSnapshots()

            await expectLogic(logic).toDispatchActions(['loadRecordingMetaSuccess', 'loadRecordingSnapshotsFailure'])
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
            logic.actions.loadRecordingMeta()
            await expectLogic(logic).toFinishAllListeners()
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
                logic.actions.loadRecordingSnapshots()
            }).toDispatchActions(['loadEvents', 'loadEventsSuccess'])

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
                        personId: '11',
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

    describe('force upgrade of session recording snapshots endpoint', () => {
        it('can force upgrade by returning 302', async () => {
            logic = sessionRecordingDataLogic({ sessionRecordingId: 'forced_upgrade' })
            logic.mount()
            // Most of these tests assume the metadata is being loaded upfront which is the typical case
            logic.actions.loadRecordingMeta()

            await expectLogic(logic, () => {
                logic.actions.loadRecordingSnapshots()
            })
                .toDispatchActions([
                    'loadRecordingSnapshotsV1Success',
                    'loadRecordingSnapshotsV2',
                    'loadRecordingSnapshotsV2Success',
                ])
                .toMatchValues({
                    sessionPlayerSnapshotData: {
                        snapshots: [],
                        sources: [
                            {
                                loaded: true,
                                source: 'blob',
                                start_timestamp: '2023-08-11T12:03:36.097000Z',
                                end_timestamp: '2023-08-11T12:04:52.268000Z',
                                blob_key: '1691755416097-1691755492268',
                            },
                        ],
                    },
                })
        })
    })

    describe('loading session snapshots', () => {
        beforeEach(async () => {
            await expectLogic(logic).toDispatchActions(['loadRecordingMetaSuccess'])
        })

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
            logic.actions.loadRecordingMeta()
            await expectLogic(logic).toDispatchActions(['loadRecordingMetaSuccess'])
            api.get.mockClear()
            logic.actions.loadRecordingSnapshots()
            await expectLogic(logic).toMount([eventUsageLogic]).toFinishAllListeners()
            await expectLogic(logic).toDispatchActions(['loadRecordingSnapshotsV1', 'loadRecordingSnapshotsV1Success'])

            await expectLogic(logic)
                .toDispatchActions([
                    logic.actionCreators.loadRecordingSnapshotsV1(firstNext),
                    'loadRecordingSnapshotsV1Success',
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
            expect(api.get).toBeCalledTimes(2) // 2 calls to loadRecordingSnapshots
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
            logic.actions.loadRecordingMeta()

            await expectLogic(logic).toDispatchActions(['loadRecordingMetaSuccess'])
            await expectLogic(logic).toMount([eventUsageLogic]).toFinishAllListeners()
            api.get.mockClear()

            const snapshotUrl = createSnapshotEndpoint(1)
            const firstNext = `${snapshotUrl}/?offset=200&limit=200`
            silenceKeaLoadersErrors()

            await expectLogic(logic, () => {
                logic.actions.loadRecordingSnapshots()
            }).toDispatchActions(['loadRecordingSnapshotsV1', 'loadRecordingSnapshotsV1Success'])

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
                    logic.actionCreators.loadRecordingSnapshotsV1(firstNext),
                    'loadRecordingSnapshotsV1Failure',
                ])
                .toFinishAllListeners()
            resumeKeaLoadersErrors()
            expect(api.get).toHaveBeenCalledWith(firstNext)
        })
    })

    describe('report usage', () => {
        it('send `recording loaded` event only when entire recording has loaded', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadRecordingSnapshots()
            })
                .toDispatchActionsInAnyOrder([
                    'loadRecordingSnapshotsV1',
                    'loadRecordingSnapshotsV1Success',
                    'loadEvents',
                    'loadEventsSuccess',
                ])
                .toDispatchActions([eventUsageLogic.actionTypes.reportRecording])
        })
        it('send `recording viewed` and `recording analyzed` event on first contentful paint', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadRecordingSnapshots()
            })
                .toDispatchActions(['loadRecordingSnapshotsSuccess'])
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
