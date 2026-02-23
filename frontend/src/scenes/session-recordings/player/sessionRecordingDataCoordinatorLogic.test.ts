import { api } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { sessionRecordingDataCoordinatorLogic } from 'scenes/session-recordings/player/sessionRecordingDataCoordinatorLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { HogQLQueryResponse } from '~/queries/schema/schema-general'

import { sessionRecordingEventUsageLogic } from '../sessionRecordingEventUsageLogic'
import {
    createDifferentiatedQueryHandler,
    overrideSessionRecordingMocks,
    recordingEventsJson,
    recordingMetaJson,
    setupSessionRecordingTest,
} from './__mocks__/test-setup'
import { snapshotDataLogic } from './snapshotDataLogic'

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
            expect(actual.person).toEqual(recordingMetaJson.person)
            expect(actual.fullyLoaded).toBe(true)
            expect(Object.keys(actual.snapshotsByWindowId).length).toBeGreaterThan(0)
            const totalSnapshots = Object.values(actual.snapshotsByWindowId).reduce((sum, arr) => sum + arr.length, 0)
            expect(totalSnapshots).toBeGreaterThan(0)
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
})
