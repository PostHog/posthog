import { EventType, IncrementalSource, mutationData, NodeType } from '@posthog/rrweb-types'
import { expectLogic } from 'kea-test-utils'
import { api, MOCK_TEAM_ID } from 'lib/api.mock'
import { convertSnapshotsByWindowId } from 'scenes/session-recordings/__mocks__/recording_snapshots'
import { encodedWebSnapshotData } from 'scenes/session-recordings/player/__mocks__/encoded-snapshot-data'
import {
    parseEncodedSnapshots,
    sessionRecordingDataLogic,
} from 'scenes/session-recordings/player/sessionRecordingDataLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useAvailableFeatures } from '~/mocks/features'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AvailableFeature, RecordingSnapshot, SessionRecordingSnapshotSource } from '~/types'

import recordingEventsJson from '../__mocks__/recording_events_query'
import { recordingMetaJson } from '../__mocks__/recording_meta'
import { snapshotsAsJSONLines, sortedRecordingSnapshots } from '../__mocks__/recording_snapshots'
import { sessionRecordingEventUsageLogic } from '../sessionRecordingEventUsageLogic'
import { chunkMutationSnapshot } from './snapshot-processing/chunk-large-mutations'
import { MUTATION_CHUNK_SIZE } from './snapshot-processing/chunk-large-mutations'
import { deduplicateSnapshots } from './snapshot-processing/deduplicate-snapshots'

const sortedRecordingSnapshotsJson = sortedRecordingSnapshots()

const BLOB_SOURCE: SessionRecordingSnapshotSource = {
    source: 'blob',
    start_timestamp: '2023-08-11T12:03:36.097000Z',
    end_timestamp: '2023-08-11T12:04:52.268000Z',
    blob_key: '1691755416097-1691755492268',
}
const REALTIME_SOURCE: SessionRecordingSnapshotSource = {
    source: 'realtime',
    start_timestamp: '2024-01-28T21:19:49.217000Z',
    end_timestamp: undefined,
    blob_key: undefined,
}

describe('sessionRecordingDataLogic', () => {
    let logic: ReturnType<typeof sessionRecordingDataLogic.build>

    beforeEach(() => {
        useAvailableFeatures([AvailableFeature.RECORDINGS_PERFORMANCE])
        useMocks({
            get: {
                '/api/environments/:team_id/session_recordings/:id/snapshots': async (req, res, ctx) => {
                    // with no sources, returns sources...
                    if (req.url.searchParams.get('source') === 'blob') {
                        return res(ctx.text(snapshotsAsJSONLines()))
                    } else if (req.url.searchParams.get('source') === 'realtime') {
                        if (req.params.id === 'has-only-empty-realtime') {
                            return res(ctx.json([]))
                        }
                        return res(ctx.text(snapshotsAsJSONLines()))
                    }

                    // with no source requested should return sources
                    let sources = [BLOB_SOURCE]
                    if (req.params.id === 'has-real-time-too') {
                        sources.push(REALTIME_SOURCE)
                    }
                    if (req.params.id === 'has-only-empty-realtime') {
                        sources = [REALTIME_SOURCE]
                    }
                    return [
                        200,
                        {
                            sources,
                        },
                    ]
                },
                '/api/environments/:team_id/session_recordings/:id': recordingMetaJson,
            },
            post: {
                '/api/environments/:team_id/query': recordingEventsJson,
            },
            patch: {
                '/api/environments/:team_id/session_recordings/:id': { success: true },
            },
        })
        initKeaTests()
        logic = sessionRecordingDataLogic({
            sessionRecordingId: '2',
            // we don't want to wait for the default real time polling interval in tests
            realTimePollingIntervalMilliseconds: 10,
        })
        logic.mount()
        // Most of these tests assume the metadata is being loaded upfront which is the typical case
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
                filters: {},
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
                    'loadSnapshotSourcesSuccess',
                    'loadSnapshotsForSourceSuccess',
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
            // Unmount and remount the logic to trigger fetching the data again after the mock change
            logic.unmount()
            useMocks({
                get: {
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
                    '/api/environments/:team_id/session_recordings/:id/snapshots': () => [500, { status: 0 }],
                },
            })
            logic.mount()
            logic.actions.loadRecordingMeta()
            logic.actions.loadSnapshots()

            await expectLogic(logic).toDispatchActions(['loadRecordingMetaSuccess', 'loadSnapshotSourcesFailure'])
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
            logic = sessionRecordingDataLogic({
                sessionRecordingId: '2',
                // we don't want to wait for the default real time polling interval in tests
                realTimePollingIntervalMilliseconds: 10,
            })
            logic.mount()
            logic.actions.loadRecordingMeta()
            await expectLogic(logic).toFinishAllListeners()
            api.get.mockClear()
            api.create.mockClear()
        })

        it('load events after metadata with 5 minute buffer', async () => {
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
                logic.actions.loadSnapshots()
            }).toDispatchActions(['loadEvents', 'loadEventsSuccess'])

            expect(api.create).toHaveBeenCalledWith(
                `api/environments/${MOCK_TEAM_ID}/query`,
                {
                    client_query_id: undefined,
                    query: {
                        kind: 'HogQLQuery',
                        query: `
                            SELECT uuid, event, timestamp, elements_chain, properties.$window_id, properties.$current_url, properties.$event_type
                            FROM events
                            WHERE timestamp > '2023-05-01 14:41:20'
                              AND timestamp < '2023-05-01 14:51:32'
                              AND (empty($session_id) OR isNull($session_id)) AND properties.$lib != 'web'
                        
                            AND person_id = '0187d7c7-61b7-0000-d6a1-59b207080ac0'
                        
                        ORDER BY timestamp ASC
                        LIMIT 1000000
                    `,
                    },
                },
                expect.anything()
            )

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
                    'loadSnapshotsForSourceSuccess',
                    'loadEvents',
                    'loadEventsSuccess',
                ])
                .toDispatchActions([sessionRecordingEventUsageLogic.actionTypes.reportRecording])
        })
        it('sends `recording viewed` and `recording analyzed` event on first contentful paint', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadSnapshots()
            })
                .toDispatchActions(['loadSnapshotsForSourceSuccess'])
                .toDispatchActionsInAnyOrder([
                    sessionRecordingEventUsageLogic.actionTypes.reportRecording, // loaded
                    sessionRecordingEventUsageLogic.actionTypes.reportRecording, // viewed
                    sessionRecordingEventUsageLogic.actionTypes.reportRecording, // analyzed
                ])
        })
    })

    describe('deduplicateSnapshots', () => {
        it('should remove duplicate snapshots and sort by timestamp', () => {
            const snapshots = convertSnapshotsByWindowId(sortedRecordingSnapshotsJson.snapshot_data_by_window_id)
            const snapshotsWithDuplicates = snapshots
                .slice(0, 2)
                .concat(snapshots.slice(0, 2))
                .concat(snapshots.slice(2))

            expect(snapshotsWithDuplicates.length).toEqual(snapshots.length + 2)

            expect(deduplicateSnapshots(snapshots)).toEqual(deduplicateSnapshots(snapshotsWithDuplicates))
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
            expect(deduplicateSnapshots([...verySimilarSnapshots, ...verySimilarSnapshots])).toEqual(
                verySimilarSnapshots
            )
        })

        it('should match snapshot', () => {
            const snapshots = convertSnapshotsByWindowId(sortedRecordingSnapshotsJson.snapshot_data_by_window_id)

            expect(deduplicateSnapshots(snapshots)).toMatchSnapshot()
        })
    })

    describe('blob and realtime loading', () => {
        beforeEach(async () => {
            // load a different session
            logic = sessionRecordingDataLogic({
                sessionRecordingId: 'has-real-time-too',
                // we don't want to wait for the default real time polling interval in tests
                realTimePollingIntervalMilliseconds: 10,
            })
            logic.mount()
            // Most of these tests assume the metadata is being loaded upfront which is the typical case
            logic.actions.loadRecordingMeta()
        })

        it('loads each source, and on success reports recording viewed', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadSnapshots()
                // loading the snapshots will trigger a loadSnapshotsForSourceSuccess
                // that will have the blob source
                // that triggers loadNextSnapshotSource
            }).toDispatchActions([
                // the action we triggered
                'loadSnapshots',
                // the response to that triggers loading of the first item which is the blob source
                (action) =>
                    action.type === logic.actionTypes.loadSnapshotsForSource &&
                    action.payload.source?.source === 'blob',
                'loadSnapshotsForSourceSuccess',
                // and then we report having viewed the recording
                'markViewed',
                // the response to the success action triggers loading of the second item which is the realtime source
                (action) =>
                    action.type === logic.actionTypes.loadSnapshotsForSource &&
                    action.payload.source?.source === 'realtime',
                'loadSnapshotsForSourceSuccess',
                // having loaded any real time data we start polling to check for more
                'pollRealtimeSnapshots',
                // which in turn triggers another load
                (action) =>
                    action.type === logic.actionTypes.loadSnapshotsForSource &&
                    action.payload.source?.source === 'realtime',
                'loadSnapshotsForSourceSuccess',
            ])
        })
    })

    describe('empty realtime loading', () => {
        beforeEach(async () => {
            logic = sessionRecordingDataLogic({
                sessionRecordingId: 'has-only-empty-realtime',
                // we don't want to wait for the default real time polling interval in tests
                realTimePollingIntervalMilliseconds: 10,
            })
            logic.mount()
            // Most of these tests assume the metadata is being loaded upfront which is the typical case
            logic.actions.loadRecordingMeta()
        })

        it('should start polling even though realtime is empty', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadSnapshots()
            }).toDispatchActions([
                'loadSnapshots',
                'loadSnapshotSourcesSuccess',
                'loadNextSnapshotSource',
                'pollRealtimeSnapshots',
                'loadSnapshotsForSource',
                'loadSnapshotsForSourceSuccess',
            ])
        })
    })

    describe('snapshot parsing', () => {
        const sessionId = '12345'
        const numberOfParsedLinesInData = 8
        it('handles normal web data', async () => {
            const parsed = await parseEncodedSnapshots(encodedWebSnapshotData, sessionId, false)
            expect(parsed.length).toEqual(numberOfParsedLinesInData)
            expect(parsed).toMatchSnapshot()
        })

        it('handles data with unparseable lines', async () => {
            const parsed = await parseEncodedSnapshots(
                encodedWebSnapshotData.map((line, index) => {
                    return index == 0 ? line.substring(0, line.length / 2) : line
                }),
                sessionId,
                false
            )

            // unparseable lines are not returned
            expect(encodedWebSnapshotData.length).toEqual(2)
            expect(parsed.length).toEqual(numberOfParsedLinesInData / 2)

            expect(parsed).toMatchSnapshot()
        })
    })

    describe('mutation chunking', () => {
        const createMutationSnapshot = (addsCount: number): RecordingSnapshot =>
            ({
                type: EventType.IncrementalSnapshot,
                timestamp: 1000,
                data: {
                    source: IncrementalSource.Mutation,
                    adds: Array(addsCount).fill({ parentId: 1, nextId: null, node: { type: 1, tagName: 'div' } }),
                    removes: [{ parentId: 1, id: 2 }],
                    texts: [{ id: 3, value: 'text' }],
                    attributes: [{ id: 4, attributes: { class: 'test' } }],
                },
                windowId: '1',
            } as RecordingSnapshot)

        it('does not chunk snapshots with adds below chunk size', () => {
            const snapshot = createMutationSnapshot(100)
            const chunks = chunkMutationSnapshot(snapshot)
            expect(chunks).toEqual([snapshot])
        })

        it('chunks large mutation snapshots correctly', () => {
            const addsCount = MUTATION_CHUNK_SIZE * 2 + 500 // Will create 3 chunks
            const snapshot = createMutationSnapshot(addsCount)
            const chunks = chunkMutationSnapshot(snapshot)

            expect(chunks.length).toBe(3)

            // First chunk
            expect(chunks[0]).toMatchObject({
                timestamp: 1000,
                data: {
                    adds: expect.arrayContaining([expect.any(Object)]),
                    removes: (snapshot.data as mutationData).removes,
                    texts: [],
                    attributes: [],
                },
            })
            expect((chunks[0].data as mutationData).adds.length).toBe(MUTATION_CHUNK_SIZE)

            // Middle chunk
            expect(chunks[1]).toMatchObject({
                timestamp: 1000,
                data: {
                    adds: expect.arrayContaining([expect.any(Object)]),
                    removes: [],
                    texts: [],
                    attributes: [],
                },
            })
            expect((chunks[1].data as mutationData).adds.length).toBe(MUTATION_CHUNK_SIZE)

            // Last chunk
            expect(chunks[2]).toMatchObject({
                timestamp: 1000,
                data: {
                    adds: expect.arrayContaining([expect.any(Object)]),
                    removes: [],
                    texts: (snapshot.data as mutationData).texts,
                    attributes: (snapshot.data as mutationData).attributes,
                },
            })
            expect((chunks[2].data as mutationData).adds.length).toBe(500)
        })

        it('handles delay correctly when chunking', () => {
            const snapshot = createMutationSnapshot(MUTATION_CHUNK_SIZE * 2)
            snapshot.delay = 100

            const chunks = chunkMutationSnapshot(snapshot)

            expect(chunks.length).toBe(2)
            expect(chunks[0].delay).toBe(100)
            expect(chunks[1].delay).toBe(100)
        })

        it('does not chunk non-mutation snapshots', () => {
            const snapshot: RecordingSnapshot = {
                type: EventType.FullSnapshot,
                timestamp: 1000,
                data: {
                    node: { type: NodeType.Document, id: 1, childNodes: [] },
                    initialOffset: { top: 0, left: 0 },
                },
                windowId: '1',
            }
            const chunks = chunkMutationSnapshot(snapshot)
            expect(chunks).toEqual([snapshot])
        })
    })
})
