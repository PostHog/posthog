import { api } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { EventType, IncrementalSource, NodeType, mutationData } from '@posthog/rrweb-types'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { encodedWebSnapshotData } from 'scenes/session-recordings/player/__mocks__/encoded-snapshot-data'
import { parseEncodedSnapshots } from 'scenes/session-recordings/player/snapshot-processing/process-all-snapshots'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { RecordingSnapshot, SessionRecordingSnapshotSource } from '~/types'

import { overrideSessionRecordingMocks, setupSessionRecordingTest } from './__mocks__/test-setup'
import { chunkMutationSnapshot } from './snapshot-processing/chunk-large-mutations'
import { MUTATION_CHUNK_SIZE } from './snapshot-processing/chunk-large-mutations'
import { snapshotDataLogic } from './snapshotDataLogic'

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
            expect(Object.keys(snapshotsBySources)).toEqual(['blob_v2-0', 'blob_v2-1', '_count'])
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
                windowId: 1,
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
                windowId: 1,
            }
            const chunks = chunkMutationSnapshot(snapshot)
            expect(chunks).toEqual([snapshot])
        })
    })

    describe('timestamp-based loading', () => {
        const enableTimestampBasedLoading = (): void => {
            featureFlagLogic.mount()
            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.REPLAY_TIMESTAMP_BASED_LOADING]: 'test',
            })
        }

        const createBlobSources = (count: number): SessionRecordingSnapshotSource[] => {
            return Array.from({ length: count }, (_, i) => ({
                source: 'blob_v2' as const,
                start_timestamp: new Date(Date.UTC(2023, 7, 11, 12, i, 0)).toISOString(),
                end_timestamp: new Date(Date.UTC(2023, 7, 11, 12, i, 59)).toISOString(),
                blob_key: String(i),
            }))
        }

        describe('blobIndexForTimestamp selector', () => {
            it.each([
                { description: 'timestamp in first blob', targetMinute: 0, expectedIndex: 0 },
                { description: 'timestamp in middle blob', targetMinute: 5, expectedIndex: 5 },
                { description: 'timestamp in last blob', targetMinute: 9, expectedIndex: 9 },
            ])('returns correct index for $description', async ({ targetMinute, expectedIndex }) => {
                const sources = createBlobSources(10)
                setupSessionRecordingTest({ snapshotSources: sources })

                const testLogic = snapshotDataLogic({
                    sessionRecordingId: '2',
                    blobV2PollingDisabled: true,
                })
                testLogic.mount()

                await expectLogic(testLogic, () => {
                    testLogic.actions.loadSnapshots()
                }).toDispatchActions(['loadSnapshotSourcesSuccess'])

                const timestamp = new Date(Date.UTC(2023, 7, 11, 12, targetMinute, 30)).getTime()
                const index = testLogic.values.blobIndexForTimestamp(timestamp)
                expect(index).toBe(expectedIndex)
            })

            it('returns first blob for timestamp before recording', async () => {
                const sources = createBlobSources(10)
                setupSessionRecordingTest({ snapshotSources: sources })

                const testLogic = snapshotDataLogic({
                    sessionRecordingId: '2',
                    blobV2PollingDisabled: true,
                })
                testLogic.mount()

                await expectLogic(testLogic, () => {
                    testLogic.actions.loadSnapshots()
                }).toDispatchActions(['loadSnapshotSourcesSuccess'])

                const timestamp = new Date(Date.UTC(2023, 7, 11, 11, 0, 0)).getTime()
                const index = testLogic.values.blobIndexForTimestamp(timestamp)
                expect(index).toBe(0)
            })

            it('returns last blob for timestamp after recording', async () => {
                const sources = createBlobSources(10)
                setupSessionRecordingTest({ snapshotSources: sources })

                const testLogic = snapshotDataLogic({
                    sessionRecordingId: '2',
                    blobV2PollingDisabled: true,
                })
                testLogic.mount()

                await expectLogic(testLogic, () => {
                    testLogic.actions.loadSnapshots()
                }).toDispatchActions(['loadSnapshotSourcesSuccess'])

                const timestamp = new Date(Date.UTC(2023, 7, 11, 13, 0, 0)).getTime()
                const index = testLogic.values.blobIndexForTimestamp(timestamp)
                expect(index).toBe(9)
            })

            it('returns null when no sources loaded', async () => {
                setupSessionRecordingTest({ snapshotSources: [] })

                const testLogic = snapshotDataLogic({
                    sessionRecordingId: '2',
                    blobV2PollingDisabled: true,
                })
                testLogic.mount()

                const timestamp = new Date(Date.UTC(2023, 7, 11, 12, 5, 0)).getTime()
                const index = testLogic.values.blobIndexForTimestamp(timestamp)
                expect(index).toBe(null)
            })
        })

        describe('loading phase state machine', () => {
            it('starts in sequential phase by default', async () => {
                setupSessionRecordingTest({ snapshotSources: createBlobSources(10) })

                const testLogic = snapshotDataLogic({
                    sessionRecordingId: '2',
                    blobV2PollingDisabled: true,
                })
                testLogic.mount()

                expect(testLogic.values.loadingPhase).toBe('sequential')
            })

            it('can set target timestamp', async () => {
                setupSessionRecordingTest({ snapshotSources: createBlobSources(10) })

                const testLogic = snapshotDataLogic({
                    sessionRecordingId: '2',
                    blobV2PollingDisabled: true,
                })
                testLogic.mount()

                const targetTime = new Date(Date.UTC(2023, 7, 11, 12, 5, 0)).getTime()
                testLogic.actions.setTargetTimestamp(targetTime)

                expect(testLogic.values.targetTimestamp).toBe(targetTime)
            })

            it('can set loading phase', async () => {
                setupSessionRecordingTest({ snapshotSources: createBlobSources(10) })

                const testLogic = snapshotDataLogic({
                    sessionRecordingId: '2',
                    blobV2PollingDisabled: true,
                })
                testLogic.mount()

                testLogic.actions.setLoadingPhase('find_target')
                expect(testLogic.values.loadingPhase).toBe('find_target')

                testLogic.actions.setLoadingPhase('find_fullsnapshot')
                expect(testLogic.values.loadingPhase).toBe('find_fullsnapshot')
            })

            it('resetTimestampLoading resets state', async () => {
                setupSessionRecordingTest({ snapshotSources: createBlobSources(10) })

                const testLogic = snapshotDataLogic({
                    sessionRecordingId: '2',
                    blobV2PollingDisabled: true,
                })
                testLogic.mount()

                testLogic.actions.setTargetTimestamp(12345)
                testLogic.actions.setLoadingPhase('find_fullsnapshot')

                testLogic.actions.resetTimestampLoading()

                expect(testLogic.values.targetTimestamp).toBe(null)
                expect(testLogic.values.loadingPhase).toBe('sequential')
            })
        })

        describe('hasPlayableFullSnapshot selector', () => {
            it('returns true when no target timestamp', async () => {
                setupSessionRecordingTest({ snapshotSources: createBlobSources(2) })

                const testLogic = snapshotDataLogic({
                    sessionRecordingId: '2',
                    blobV2PollingDisabled: true,
                })
                testLogic.mount()

                expect(testLogic.values.hasPlayableFullSnapshot).toBe(true)
            })

            it('returns false when there is a gap between FullSnapshot blob and target blob', async () => {
                // Scenario: User seeks to blob 5 (loads 2-12 with FullSnapshot in blob 4)
                // Then seeks to blob 27 (loads 25-35)
                // FullSnapshot in blob 4 should NOT be playable for target in blob 27
                // because blobs 13-24 are not loaded
                const sources = createBlobSources(40)
                setupSessionRecordingTest({ snapshotSources: sources })
                enableTimestampBasedLoading()

                const testLogic = snapshotDataLogic({
                    sessionRecordingId: '2',
                    blobV2PollingDisabled: true,
                })
                testLogic.mount()

                // Load sources metadata
                await expectLogic(testLogic, () => {
                    testLogic.actions.loadSnapshots()
                }).toDispatchActions(['loadSnapshotSourcesSuccess'])

                // Simulate: first seek loads blobs 2-12
                await expectLogic(testLogic, () => {
                    testLogic.actions.loadSnapshotsForSource(sources.slice(2, 13))
                }).toDispatchActions(['loadSnapshotsForSourceSuccess'])

                // Simulate: second seek to blob 27, loads blobs 25-35
                await expectLogic(testLogic, () => {
                    testLogic.actions.loadSnapshotsForSource(sources.slice(25, 36))
                }).toDispatchActions(['loadSnapshotsForSourceSuccess'])

                // Set target timestamp to blob 27
                const targetTime = new Date(Date.UTC(2023, 7, 11, 12, 27, 30)).getTime()
                testLogic.actions.setTargetTimestamp(targetTime)

                // FullSnapshot exists in loaded data (from blobs 2-12) but there's a gap
                // between blob 12 and blob 25, so it should NOT be playable
                expect(testLogic.values.hasPlayableFullSnapshot).toBe(false)
            })

            it('returns true when FullSnapshot blob has continuous coverage to target', async () => {
                const sources = createBlobSources(10)
                setupSessionRecordingTest({ snapshotSources: sources })
                enableTimestampBasedLoading()

                const testLogic = snapshotDataLogic({
                    sessionRecordingId: '2',
                    blobV2PollingDisabled: true,
                })
                testLogic.mount()

                // Load all blobs 0-9 (continuous coverage)
                await expectLogic(testLogic, () => {
                    testLogic.actions.loadSnapshots()
                }).toFinishAllListeners()

                // Set target timestamp to blob 7
                const targetTime = new Date(Date.UTC(2023, 7, 11, 12, 7, 30)).getTime()
                testLogic.actions.setTargetTimestamp(targetTime)

                // Should be playable because we have continuous coverage
                expect(testLogic.values.hasPlayableFullSnapshot).toBe(true)
            })
        })

        describe('with feature flag enabled', () => {
            it('transitions to sequential after finding playable FullSnapshot', async () => {
                const sources = createBlobSources(10)
                setupSessionRecordingTest({ snapshotSources: sources })
                enableTimestampBasedLoading()

                const testLogic = snapshotDataLogic({
                    sessionRecordingId: '2',
                    blobV2PollingDisabled: true,
                })
                testLogic.mount()

                const targetTime = new Date(Date.UTC(2023, 7, 11, 12, 5, 30)).getTime()
                testLogic.actions.setTargetTimestamp(targetTime)
                testLogic.actions.setLoadingPhase('find_target')

                await expectLogic(testLogic, () => {
                    testLogic.actions.loadSnapshots()
                }).toDispatchActions([
                    'loadSnapshotSourcesSuccess',
                    'loadSnapshotsForSource',
                    'loadSnapshotsForSourceSuccess',
                    // After initial batch loaded, transitions to find_fullsnapshot
                    (action) =>
                        action.type === testLogic.actionTypes.setLoadingPhase &&
                        action.payload.phase === 'find_fullsnapshot',
                    // Loads backward blobs to find FullSnapshot, then switches to sequential
                    (action) =>
                        action.type === testLogic.actionTypes.setLoadingPhase && action.payload.phase === 'sequential',
                ])
            })

            it.each([
                { targetMinute: 5, expectedStartKey: '3', expectedBatchSize: 7, description: 'middle of recording' },
                { targetMinute: 0, expectedStartKey: '0', expectedBatchSize: 8, description: 'start of recording' },
                { targetMinute: 9, expectedStartKey: '7', expectedBatchSize: 3, description: 'end of recording' },
            ])(
                'loads correct blob range for $description (target-2 to target+7)',
                async ({ targetMinute, expectedStartKey, expectedBatchSize }) => {
                    const sources = createBlobSources(10)
                    setupSessionRecordingTest({ snapshotSources: sources })
                    enableTimestampBasedLoading()

                    const testLogic = snapshotDataLogic({
                        sessionRecordingId: '2',
                        blobV2PollingDisabled: true,
                    })
                    testLogic.mount()

                    const targetTime = new Date(Date.UTC(2023, 7, 11, 12, targetMinute, 30)).getTime()
                    testLogic.actions.setTargetTimestamp(targetTime)
                    testLogic.actions.setLoadingPhase('find_target')

                    await expectLogic(testLogic, () => {
                        testLogic.actions.loadSnapshots()
                    }).toDispatchActions([
                        'loadSnapshotSourcesSuccess',
                        (action) =>
                            action.type === testLogic.actionTypes.loadSnapshotsForSource &&
                            action.payload.sources?.[0]?.blob_key === expectedStartKey &&
                            action.payload.sources?.length === expectedBatchSize,
                    ])
                }
            )

            it('uses sequential loading when feature flag is control', async () => {
                const sources = createBlobSources(10)
                setupSessionRecordingTest({ snapshotSources: sources })
                featureFlagLogic.mount()
                featureFlagLogic.actions.setFeatureFlags([], {
                    [FEATURE_FLAGS.REPLAY_TIMESTAMP_BASED_LOADING]: 'control',
                })

                const testLogic = snapshotDataLogic({
                    sessionRecordingId: '2',
                    blobV2PollingDisabled: true,
                })
                testLogic.mount()

                const targetTime = new Date(Date.UTC(2023, 7, 11, 12, 5, 30)).getTime()
                testLogic.actions.setTargetTimestamp(targetTime)
                testLogic.actions.setLoadingPhase('find_target')

                await expectLogic(testLogic, () => {
                    testLogic.actions.loadSnapshots()
                }).toDispatchActions([
                    'loadSnapshotSourcesSuccess',
                    (action) =>
                        action.type === testLogic.actionTypes.loadSnapshotsForSource &&
                        action.payload.sources?.[0]?.blob_key === '0',
                ])
            })

            it('ends in sequential phase after full loading cycle', async () => {
                const sources = createBlobSources(10)
                setupSessionRecordingTest({ snapshotSources: sources })
                enableTimestampBasedLoading()

                const testLogic = snapshotDataLogic({
                    sessionRecordingId: '2',
                    blobV2PollingDisabled: true,
                })
                testLogic.mount()

                const targetTime = new Date(Date.UTC(2023, 7, 11, 12, 5, 30)).getTime()
                testLogic.actions.setTargetTimestamp(targetTime)
                testLogic.actions.setLoadingPhase('find_target')

                await expectLogic(testLogic, () => {
                    testLogic.actions.loadSnapshots()
                }).toFinishAllListeners()

                // Mock data includes FullSnapshot, so it should find it and transition to sequential
                expect(testLogic.values.loadingPhase).toBe('sequential')
                expect(testLogic.values.hasPlayableFullSnapshot).toBe(true)
            })

            it('recordPlayabilityMarkers accumulates and deduplicates markers', () => {
                setupSessionRecordingTest({ snapshotSources: createBlobSources(10) })
                enableTimestampBasedLoading()

                const testLogic = snapshotDataLogic({
                    sessionRecordingId: '2',
                    blobV2PollingDisabled: true,
                })
                testLogic.mount()

                testLogic.actions.recordPlayabilityMarkers({
                    fullSnapshots: [1000, 2000],
                    metas: [900],
                })
                testLogic.actions.recordPlayabilityMarkers({
                    fullSnapshots: [2000, 3000],
                    metas: [900, 1900],
                })

                const markers = testLogic.values.playabilityMarkers
                // Deduplicates and sorts
                expect(markers.fullSnapshots).toEqual([1000, 2000, 3000])
                expect(markers.metas).toEqual([900, 1900])
            })

            it('playability markers persist across resetTimestampLoading', () => {
                setupSessionRecordingTest({ snapshotSources: createBlobSources(10) })
                enableTimestampBasedLoading()

                const testLogic = snapshotDataLogic({
                    sessionRecordingId: '2',
                    blobV2PollingDisabled: true,
                })
                testLogic.mount()

                testLogic.actions.recordPlayabilityMarkers({
                    fullSnapshots: [1000, 2000],
                    metas: [900],
                })

                testLogic.actions.setTargetTimestamp(5000)
                testLogic.actions.setLoadingPhase('find_fullsnapshot')
                testLogic.actions.resetTimestampLoading()

                // Markers survive reset — they're metadata about the recording, not loading state
                expect(testLogic.values.playabilityMarkers).toEqual({
                    fullSnapshots: [1000, 2000],
                    metas: [900],
                })
                // But loading state is reset
                expect(testLogic.values.targetTimestamp).toBe(null)
                expect(testLogic.values.loadingPhase).toBe('sequential')
            })

            it('fills gaps backward from target toward FullSnapshot blob', async () => {
                const sources = createBlobSources(10)
                setupSessionRecordingTest({ snapshotSources: sources })
                enableTimestampBasedLoading()

                const testLogic = snapshotDataLogic({
                    sessionRecordingId: '2',
                    blobV2PollingDisabled: true,
                })
                testLogic.mount()

                const targetTime = new Date(Date.UTC(2023, 7, 11, 12, 5, 30)).getTime()
                testLogic.actions.setTargetTimestamp(targetTime)
                testLogic.actions.setLoadingPhase('find_target')

                await expectLogic(testLogic, () => {
                    testLogic.actions.loadSnapshots()
                }).toDispatchActions([
                    'loadSnapshotSourcesSuccess',
                    // 1. Initial window around target (target-2 to target+7): blobs 3-9
                    (action) =>
                        action.type === testLogic.actionTypes.loadSnapshotsForSource &&
                        action.payload.sources[0]?.blob_key === '3' &&
                        action.payload.sources.length === 7,
                    'loadSnapshotsForSourceSuccess',
                    // 2. Gap fill between FullSnapshot blob (0) and loaded range start (3): blobs 1-2
                    (action) =>
                        action.type === testLogic.actionTypes.loadSnapshotsForSource &&
                        action.payload.sources[0]?.blob_key === '1' &&
                        action.payload.sources.length === 2,
                    'loadSnapshotsForSourceSuccess',
                    // 3. Backward search for remaining blob before gap: blob 0
                    (action) =>
                        action.type === testLogic.actionTypes.loadSnapshotsForSource &&
                        action.payload.sources[0]?.blob_key === '0' &&
                        action.payload.sources.length === 1,
                    'loadSnapshotsForSourceSuccess',
                    // FullSnapshot now has continuous coverage → sequential
                    (action) =>
                        action.type === testLogic.actionTypes.setLoadingPhase && action.payload.phase === 'sequential',
                ])
            })

            it('isWaitingForPlayableFullSnapshot reflects target and playability state', async () => {
                setupSessionRecordingTest({ snapshotSources: createBlobSources(10) })
                enableTimestampBasedLoading()

                const testLogic = snapshotDataLogic({
                    sessionRecordingId: '2',
                    blobV2PollingDisabled: true,
                })
                testLogic.mount()

                // No target — not waiting
                expect(testLogic.values.isWaitingForPlayableFullSnapshot).toBe(false)

                // Load sources metadata so hasPlayableFullSnapshot doesn't default to true
                await expectLogic(testLogic, () => {
                    testLogic.actions.loadSnapshots()
                }).toDispatchActions(['loadSnapshotSourcesSuccess'])

                // Set target — no playable FullSnapshot yet (no blobs loaded, no markers recorded)
                const targetTime = new Date(Date.UTC(2023, 7, 11, 12, 5, 30)).getTime()
                testLogic.actions.setTargetTimestamp(targetTime)
                expect(testLogic.values.isWaitingForPlayableFullSnapshot).toBe(true)

                // Clear target — not waiting again
                testLogic.actions.resetTimestampLoading()
                expect(testLogic.values.isWaitingForPlayableFullSnapshot).toBe(false)
            })
        })
    })
})
