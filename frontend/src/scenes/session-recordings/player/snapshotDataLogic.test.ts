import { api } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { EventType, IncrementalSource, NodeType, mutationData } from '@posthog/rrweb-types'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { encodedWebSnapshotData } from 'scenes/session-recordings/player/__mocks__/encoded-snapshot-data'
import { parseEncodedSnapshots } from 'scenes/session-recordings/player/snapshot-processing/process-all-snapshots'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { RecordingSnapshot, SessionRecordingSnapshotSource } from '~/types'

import { overrideSessionRecordingMocks, setupSessionRecordingTest } from './__mocks__/test-setup'
import { chunkMutationSnapshot } from './snapshot-processing/chunk-large-mutations'
import { MUTATION_CHUNK_SIZE } from './snapshot-processing/chunk-large-mutations'
import { DEFAULT_LOADING_BUFFER, snapshotDataLogic } from './snapshotDataLogic'

const BLOB_SOURCE: SessionRecordingSnapshotSource = {
    source: 'blob_v2',
    start_timestamp: '2023-08-11T12:03:36.097000Z',
    end_timestamp: '2023-08-11T12:04:52.268000Z',
    blob_key: '0',
}
const BLOB_SOURCE_TWO: SessionRecordingSnapshotSource = {
    source: 'blob_v2',
    start_timestamp: '2023-08-11T12:04:53.097000Z',
    end_timestamp: '2023-08-11T12:04:56.268000Z',
    blob_key: '1',
}

describe('snapshotDataLogic', () => {
    let logic: ReturnType<typeof snapshotDataLogic.build>

    beforeEach(() => {
        setupSessionRecordingTest({
            snapshotSources: [BLOB_SOURCE, BLOB_SOURCE_TWO],
        })
        logic = snapshotDataLogic({
            sessionRecordingId: '2',
            blobV2PollingDisabled: true,
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
            expect(Object.keys(snapshotsBySources).length).toBe(2)
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
            logic.actions.loadSnapshots()
            await expectLogic(logic).toDispatchActions(['loadSnapshotSourcesFailure'])
            resumeKeaLoadersErrors()
        })
    })

    describe('blob loading', () => {
        beforeEach(async () => {
            // load a different session
            logic = snapshotDataLogic({
                sessionRecordingId: '2',
                blobV2PollingDisabled: true,
            })
            logic.mount()
        })

        it('loads each source', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadSnapshots()
                // loading the snapshots will trigger a loadSnapshotsForSourceSuccess
                // that will have the blob source
                // that triggers loadNextSnapshotSource
            }).toDispatchActions([
                // the action we triggered
                'loadSnapshots',
                // the response to that triggers loading of the first item which is the blob source
                // we load more than one at a time
                (action) =>
                    action.type === logic.actionTypes.loadSnapshotsForSource &&
                    action.payload.sources?.length === 2 &&
                    action.payload.sources?.[0]?.source === 'blob_v2' &&
                    action.payload.sources?.[1]?.source === 'blob_v2',
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

    describe('progressive loading and polling', () => {
        const baseTimestamp = new Date('2023-08-11T12:00:00.000Z').getTime()
        const createSource = (index: number): SessionRecordingSnapshotSource => ({
            source: 'blob_v2',
            start_timestamp: new Date(baseTimestamp + index * 60000).toISOString(),
            end_timestamp: new Date(baseTimestamp + (index + 1) * 60000 - 1).toISOString(),
            blob_key: `${index}`,
        })

        const testCases: Array<{
            description: string
            sources: SessionRecordingSnapshotSource[]
            targetTimestamp: number | null
            expectedAllSourcesLoaded: boolean
        }> = [
            {
                description:
                    'allSourcesLoaded should be true - quick fix loads all sources regardless of targetTimestamp',
                sources: [createSource(0), createSource(1), createSource(20)],
                targetTimestamp: baseTimestamp + DEFAULT_LOADING_BUFFER,
                expectedAllSourcesLoaded: true, // Changed from false - we now load all sources to prevent buffering issues
            },
            {
                description: 'allSourcesLoaded should be true when all sources are loaded without targetTimestamp',
                sources: [createSource(0), createSource(1)],
                targetTimestamp: null,
                expectedAllSourcesLoaded: true,
            },
            {
                description:
                    'allSourcesLoaded should be true when all sources are loaded with targetTimestamp beyond all sources',
                sources: [createSource(0), createSource(1)],
                targetTimestamp: baseTimestamp + 10 * 60000,
                expectedAllSourcesLoaded: true,
            },
        ]

        testCases.forEach(({ description, sources, targetTimestamp, expectedAllSourcesLoaded }) => {
            it(description, async () => {
                setupSessionRecordingTest({
                    snapshotSources: sources,
                })
                logic = snapshotDataLogic({
                    sessionRecordingId: '2',
                    blobV2PollingDisabled: true,
                })
                logic.mount()

                if (targetTimestamp) {
                    logic.actions.loadUntilTimestamp(targetTimestamp)
                }

                await expectLogic(logic, () => {
                    logic.actions.loadSnapshots()
                })
                    .toDispatchActions(['loadSnapshotsForSourceSuccess'])
                    .toFinishAllListeners()

                expect(logic.values.allSourcesLoaded).toBe(expectedAllSourcesLoaded)
            })
        })
    })
})
