import {
    prepareRecordingSnapshots,
    sessionRecordingDataLogic,
    convertSnapshotsByWindowId,
} from 'scenes/session-recordings/player/sessionRecordingDataLogic'
import { api, MOCK_TEAM_ID } from 'lib/api.mock'
import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import recordingMetaJson from '../__mocks__/recording_meta.json'
import recordingEventsJson from '../__mocks__/recording_events_query'
import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'
import { AvailableFeature } from '~/types'
import { useAvailableFeatures } from '~/mocks/features'

import { snapshotsAsJSONLines, sortedRecordingSnapshots } from '../__mocks__/recording_snapshots'

const sortedRecordingSnapshotsJson = sortedRecordingSnapshots()

describe('sessionRecordingDataLogic', () => {
    let logic: ReturnType<typeof sessionRecordingDataLogic.build>

    beforeEach(() => {
        useAvailableFeatures([AvailableFeature.RECORDINGS_PERFORMANCE])
        useMocks({
            get: {
                '/api/projects/:team/session_recordings/:id/snapshots': async (req, res, ctx) => {
                    // with no sources, returns sources...
                    if (req.url.searchParams.get('source') === 'blob') {
                        return res(ctx.text(snapshotsAsJSONLines()))
                    }
                    // with no source requested should return sources
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
        it('has default values', () => {
            expect(logic.values).toMatchObject({
                bufferedToTime: null,
                durationMs: 0,
                start: undefined,
                end: undefined,
                segments: [],
                sessionEventsData: null,
                filters: {},
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

            const actual = logic.values.sessionPlayerData
            expect(actual).toMatchObject({
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
                        personId: undefined,
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

    describe('report usage', () => {
        it('send `recording loaded` event only when entire recording has loaded', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadRecordingSnapshots()
            })
                .toDispatchActionsInAnyOrder([
                    'loadRecordingSnapshots',
                    'loadRecordingSnapshotsSuccess',
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
        })
    })

    describe('prepareRecordingSnapshots', () => {
        it('should remove duplicate snapshots and sort by timestamp', () => {
            const snapshots = convertSnapshotsByWindowId(sortedRecordingSnapshotsJson.snapshot_data_by_window_id)
            const snapshotsWithDuplicates = snapshots
                .slice(0, 2)
                .concat(snapshots.slice(0, 2))
                .concat(snapshots.slice(2))

            expect(snapshotsWithDuplicates.length).toEqual(snapshots.length + 2)

            expect(prepareRecordingSnapshots(snapshots)).toEqual(prepareRecordingSnapshots(snapshotsWithDuplicates))
        })

        it('should match snapshot', () => {
            const snapshots = convertSnapshotsByWindowId(sortedRecordingSnapshotsJson.snapshot_data_by_window_id)

            expect(prepareRecordingSnapshots(snapshots)).toMatchSnapshot()
        })
    })
})
