import { api } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { convertSnapshotsByWindowId } from 'scenes/session-recordings/__mocks__/recording_snapshots'
import { sessionRecordingDataCoordinatorLogic } from 'scenes/session-recordings/player/sessionRecordingDataCoordinatorLogic'
import { ViewportResolution } from 'scenes/session-recordings/player/snapshot-processing/patch-meta-event'
import { processAllSnapshots } from 'scenes/session-recordings/player/snapshot-processing/process-all-snapshots'
import { SourceKey } from 'scenes/session-recordings/player/snapshot-processing/source-key'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { HogQLQueryResponse } from '~/queries/schema/schema-general'
import {
    RecordingSnapshot,
    SessionRecordingSnapshotSource,
    SessionRecordingSnapshotSourceResponse,
    SnapshotSourceType,
} from '~/types'

import { sortedRecordingSnapshots } from '../__mocks__/recording_snapshots'
import { sessionRecordingEventUsageLogic } from '../sessionRecordingEventUsageLogic'
import {
    createDifferentiatedQueryHandler,
    overrideSessionRecordingMocks,
    recordingEventsJson,
    recordingMetaJson,
    setupSessionRecordingTest,
} from './__mocks__/test-setup'
import { snapshotDataLogic } from './snapshotDataLogic'

const sortedRecordingSnapshotsJson = sortedRecordingSnapshots()

describe('sessionRecordingDataCoordinatorLogic', () => {
    let logic: ReturnType<typeof sessionRecordingDataCoordinatorLogic.build>
    let snapshotLogic: ReturnType<typeof snapshotDataLogic.build>

    beforeEach(() => {
        setupSessionRecordingTest()

        const props = {
            sessionRecordingId: '2',
            blobV2PollingDisabled: true,
        }
        logic = sessionRecordingDataCoordinatorLogic(props)
        snapshotLogic = snapshotDataLogic(props)
        logic.mount()
        logic.actions.loadRecordingMeta()
        jest.spyOn(api, 'get')
        jest.spyOn(api, 'create')
    })

    describe('core assumptions', () => {
        it('mounts other logics', async () => {
            await expectLogic(logic).toMount([sessionRecordingEventUsageLogic, teamLogic, userLogic])
        })
        it('has default values', () => {
            expect(logic.values).toMatchObject({
                bufferedToTime: null,
                durationMs: 0,
                start: null,
                end: null,
                segments: [],
                sessionEventsData: null,
                sessionEventsDataLoading: false,
            })
        })
    })

    describe('loading session core', () => {
        it('loads all data', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadRecordingMeta()
                logic.actions.loadSnapshots()
            })
                .toDispatchActions([
                    'loadSnapshots',
                    'loadSnapshotSources',
                    'loadRecordingMetaSuccess',
                    snapshotLogic.actionTypes.loadSnapshotSourcesSuccess,
                    snapshotLogic.actionTypes.loadSnapshotsForSourceSuccess,
                    'reportUsageIfFullyLoaded',
                ])
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
            logic.unmount()
            overrideSessionRecordingMocks({
                getMocks: {
                    '/api/environments/:team_id/session_recordings/:id': () => [500, { status: 0 }],
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
                        start: null,
                        end: null,
                        durationMs: 0,
                        segments: [],
                        sessionRecordingId: '2',
                        sessionRetentionPeriodDays: null,
                        person: null,
                        snapshotsByWindowId: {},
                        fullyLoaded: false,
                    },
                })
            resumeKeaLoadersErrors()
        })

        it('fetch metadata success and snapshots error', async () => {
            silenceKeaLoadersErrors()
            logic.unmount()
            overrideSessionRecordingMocks({
                getMocks: {
                    '/api/environments/:team_id/session_recordings/:id/snapshots': () => [500, { status: 0 }],
                },
            })
            logic.mount()
            logic.actions.loadRecordingMeta()
            logic.actions.loadSnapshots()

            await expectLogic(logic).toDispatchActions([
                'loadRecordingMetaSuccess',
                snapshotLogic.actionTypes.loadSnapshotSourcesFailure,
            ])
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
            logic?.unmount()
            snapshotLogic?.unmount()

            setupSessionRecordingTest({
                features: [],
                customQueryHandler: createDifferentiatedQueryHandler(),
            })

            const props = {
                sessionRecordingId: '2',
                blobV2PollingDisabled: true,
            }
            logic = sessionRecordingDataCoordinatorLogic(props)
            snapshotLogic = snapshotDataLogic(props)
            logic.mount()
            jest.spyOn(api, 'get')
            jest.spyOn(api, 'create')
        })

        it('load events after metadata with 5 minute buffer', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadRecordingMeta()
            })
                .toDispatchActions(['loadRecordingMetaSuccess', 'loadEvents'])
                .toFinishAllListeners()

            expect(api.create).toHaveBeenCalledTimes(2)

            const queries = (api.create as jest.MockedFunction<typeof api.create>).mock.calls.map(
                (call) => (call[1] as { query: HogQLQueryResponse })?.query?.query
            )

            // queries 0 varies 24 hours around start time
            expect(queries[0]).toMatch(/WHERE timestamp > '2023-04-30 14:46:20'/)
            expect(queries[0]).toMatch(/AND timestamp < '2023-05-02 14:46:32'/)

            // queries one varies 5 minutes around start time
            expect(queries[1]).toMatch(/WHERE timestamp > '2023-05-01 14:41:20'/)
            expect(queries[1]).toMatch(/AND timestamp < '2023-05-01 14:51:32'/)

            expect(api.create.mock.calls).toMatchSnapshot()
            expect(logic.values.sessionEventsData).toHaveLength(recordingEventsJson.results.length)
        })
    })

    describe('report usage', () => {
        it('sends `recording loaded` event only when entire recording has loaded', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadSnapshots()
            })
                .toDispatchActionsInAnyOrder([
                    'loadSnapshots',
                    snapshotLogic.actionTypes.loadSnapshotsForSourceSuccess,
                    'loadEvents',
                    'loadEventsSuccess',
                    'loadRecordingCommentsSuccess',
                    'loadRecordingNotebookCommentsSuccess',
                ])
                .toDispatchActions([sessionRecordingEventUsageLogic.actionTypes.reportRecordingLoaded])
        })
    })

    // TODO need deduplication tests for blob_v2 sources before we deprecate blob_v1
    describe('deduplicateSnapshots', () => {
        const sources: SessionRecordingSnapshotSource[] = [
            {
                source: 'blob',
                start_timestamp: '2025-05-14T15:37:18.897000Z',
                end_timestamp: '2025-05-14T15:42:18.378000Z',
                blob_key: '1',
            },
        ]

        const fakeViewportForTimestamp: (timestamp: number) => ViewportResolution | undefined = () => ({
            width: '100',
            height: '100',
            href: '',
        })

        const callProcessing = (snapshots: RecordingSnapshot[]): RecordingSnapshot[] | undefined => {
            return processAllSnapshots(
                sources,
                {
                    'blob-1': {
                        source: { source: SnapshotSourceType.blob_v2, blob_key: 'blob-1' },
                        snapshots,
                    },
                } as Record<SourceKey, SessionRecordingSnapshotSourceResponse> | null,
                {},
                fakeViewportForTimestamp,
                '12345'
            )
        }

        it('should remove duplicate snapshots and sort by timestamp', () => {
            const snapshots = convertSnapshotsByWindowId(sortedRecordingSnapshotsJson.snapshot_data_by_window_id)
            const snapshotsWithDuplicates = snapshots
                .slice(0, 2)
                .concat(snapshots.slice(0, 2))
                .concat(snapshots.slice(2))

            expect(snapshotsWithDuplicates.length).toEqual(snapshots.length + 2)

            expect(callProcessing(snapshots)).toEqual(callProcessing(snapshotsWithDuplicates))
        })

        it('should cope with two not duplicate snapshots with the same timestamp and delay', () => {
            // these two snapshots are not duplicates but have the same timestamp and delay
            // this regression test proves that we deduplicate them against themselves
            // prior to https://github.com/PostHog/posthog/pull/20019
            // each time deduplicateSnapshots was called with this input
            // the result would be one event longer, introducing, instead of removing, a duplicate
            const verySimilarSnapshots: RecordingSnapshot[] = [
                {
                    windowId: '1',
                    type: 3,
                    data: { source: 2, type: 0, id: 33, x: 852.7421875, y: 133.1640625 },
                    timestamp: 1682952389798,
                },
                {
                    windowId: '1',
                    type: 3,
                    data: { source: 2, type: 2, id: 33, x: 852, y: 133, pointerType: 0 },
                    timestamp: 1682952389798,
                },
            ]
            // we call this multiple times and pass existing data in, so we need to make sure it doesn't change
            expect(callProcessing([...verySimilarSnapshots, ...verySimilarSnapshots])).toEqual(verySimilarSnapshots)
        })

        it('should match snapshot', () => {
            const snapshots = convertSnapshotsByWindowId(sortedRecordingSnapshotsJson.snapshot_data_by_window_id)

            expect(callProcessing(snapshots)).toMatchSnapshot()
        })
    })
})
