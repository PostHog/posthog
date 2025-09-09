import { api } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { EventType, IncrementalSource, NodeType, mutationData } from '@posthog/rrweb-types'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { encodedWebSnapshotData } from 'scenes/session-recordings/player/__mocks__/encoded-snapshot-data'
import { parseEncodedSnapshots } from 'scenes/session-recordings/player/snapshot-processing/process-all-snapshots'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useAvailableFeatures } from '~/mocks/features'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AvailableFeature, RecordingSnapshot, SessionRecordingSnapshotSource } from '~/types'

import recordingEventsJson from '../__mocks__/recording_events_query'
import { recordingMetaJson } from '../__mocks__/recording_meta'
import { snapshotsAsJSONLines } from '../__mocks__/recording_snapshots'
import { chunkMutationSnapshot } from './snapshot-processing/chunk-large-mutations'
import { MUTATION_CHUNK_SIZE } from './snapshot-processing/chunk-large-mutations'
import { snapshotDataLogic } from './snapshotDataLogic'

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

describe('snapshotDataLogic', () => {
    let logic: ReturnType<typeof snapshotDataLogic.build>

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
        logic = snapshotDataLogic({
            sessionRecordingId: '2',
            // we don't want to wait for the default real-time polling interval in tests
            realTimePollingIntervalMilliseconds: 10,
        })
        logic.mount()
        jest.spyOn(api, 'get')
        jest.spyOn(api, 'create')
    })

    describe('core assumptions', () => {
        it('mounts other logics', async () => {
            await expectLogic(logic).toMount([featureFlagLogic])
        })
        it('has default values', () => {
            expect(logic.values).toMatchObject({
                isRealtimePolling: false,
                snapshotsBySourceSuccessCount: 0,
                snapshotSources: null,
                snapshotsForSource: null,
                snapshotsLoaded: false,
            })
        })
    })

    describe('loading session core', () => {
        it('loads all data', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadSnapshots()
            })
                .toDispatchActions([
                    'loadSnapshots',
                    'loadSnapshotSources',
                    'loadSnapshotSourcesSuccess',
                    'loadSnapshotsForSourceSuccess',
                ])
                .toFinishAllListeners()

            const snapshotsBySources = logic.values.snapshotsBySources
            expect(Object.keys(snapshotsBySources).length).toBe(1)
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
            logic.actions.loadSnapshots()
            await expectLogic(logic).toDispatchActions(['loadSnapshotSourcesFailure'])
            resumeKeaLoadersErrors()
        })
    })

    describe('blob and realtime loading', () => {
        beforeEach(async () => {
            // load a different session
            logic = snapshotDataLogic({
                sessionRecordingId: 'has-real-time-too',
                // we don't want to wait for the default real time polling interval in tests
                realTimePollingIntervalMilliseconds: 10,
            })
            logic.mount()
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
                    action.payload.sources?.[0]?.source === 'blob',
                'loadSnapshotsForSourceSuccess',
                // the response to the success action triggers loading of the second item which is the realtime source
                (action) =>
                    action.type === logic.actionTypes.loadSnapshotsForSource &&
                    action.payload.sources?.[0]?.source === 'realtime',
                'loadSnapshotsForSourceSuccess',
                // having loaded any real time data we start polling to check for more
                'pollRealtimeSnapshots',
                // which in turn triggers another load
                (action) =>
                    action.type === logic.actionTypes.loadSnapshotsForSource &&
                    action.payload.sources?.[0]?.source === 'realtime',
                'loadSnapshotsForSourceSuccess',
            ])
        })
    })

    describe('empty realtime loading', () => {
        beforeEach(async () => {
            logic = snapshotDataLogic({
                sessionRecordingId: 'has-only-empty-realtime',
                // we don't want to wait for the default real time polling interval in tests
                realTimePollingIntervalMilliseconds: 10,
            })
            logic.mount()
            // Most of these tests assume the metadata is being loaded upfront which is the typical case
            // logic.actions.loadRecordingMeta()
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
            const parsed = await parseEncodedSnapshots(encodedWebSnapshotData, sessionId)
            expect(parsed.length).toEqual(numberOfParsedLinesInData)
            expect(parsed).toMatchSnapshot()
        })

        it('handles data with unparseable lines', async () => {
            const parsed = await parseEncodedSnapshots(
                encodedWebSnapshotData.map((line, index) => {
                    return index == 0 ? line.substring(0, line.length / 2) : line
                }),
                sessionId
            )

            // unparseable lines are not returned
            expect(encodedWebSnapshotData.length).toEqual(2)
            expect(parsed.length).toEqual(numberOfParsedLinesInData / 2)

            expect(parsed).toMatchSnapshot()
        })
    })

    // TODO need chunking tests for blob_v2 sources before we deprecate blob_v1
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
            }) as RecordingSnapshot

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
