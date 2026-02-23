import { api } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { EventType } from '@posthog/rrweb-types'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { RecordingSnapshot, SessionRecordingSnapshotSource } from '~/types'

import { setupSessionRecordingTest } from './__mocks__/test-setup'
import { snapshotDataLogic } from './snapshotDataLogic'

const SOURCE_A: SessionRecordingSnapshotSource = {
    source: 'blob_v2',
    start_timestamp: '2023-08-11T12:00:00.000000Z',
    end_timestamp: '2023-08-11T12:01:00.000000Z',
    blob_key: 'a',
}
const SOURCE_B: SessionRecordingSnapshotSource = {
    source: 'blob_v2',
    start_timestamp: '2023-08-11T12:01:00.000000Z',
    end_timestamp: '2023-08-11T12:02:00.000000Z',
    blob_key: 'b',
}
const SOURCE_C: SessionRecordingSnapshotSource = {
    source: 'blob_v2',
    start_timestamp: '2023-08-11T12:02:00.000000Z',
    end_timestamp: '2023-08-11T12:03:00.000000Z',
    blob_key: 'c',
}

function tsMs(minute: number, second: number = 30): number {
    return new Date(`2023-08-11T12:0${minute}:${String(second).padStart(2, '0')}.000Z`).getTime()
}

function makeSnapshot(timestamp: number, windowId: number = 1): RecordingSnapshot {
    return { timestamp, windowId, type: EventType.IncrementalSnapshot, data: {} } as unknown as RecordingSnapshot
}

function makeFullSnapshot(timestamp: number, windowId: number = 1): RecordingSnapshot {
    return {
        timestamp,
        windowId,
        type: EventType.FullSnapshot,
        data: { node: {}, initialOffset: { top: 0, left: 0 } },
    } as unknown as RecordingSnapshot
}

describe('snapshotDataLogic (store-based loading)', () => {
    let logic: ReturnType<typeof snapshotDataLogic.build>

    function mountWithStoreFlag(): void {
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.REPLAY_SNAPSHOT_STORE]: 'test',
        })
        logic = snapshotDataLogic({
            sessionRecordingId: 'store-test',
            blobV2PollingDisabled: true,
        })
        logic.mount()
    }

    beforeEach(() => {
        setupSessionRecordingTest({
            snapshotSources: [SOURCE_A, SOURCE_B, SOURCE_C],
        })
        jest.spyOn(api, 'get')
    })

    afterEach(() => {
        logic?.unmount()
        featureFlagLogic?.unmount()
    })

    describe('initialization', () => {
        it('creates store and scheduler when feature flag is set', () => {
            mountWithStoreFlag()

            expect(logic.values.snapshotStore).not.toBeNull()
            expect(logic.values.storeVersion).toBe(0)
            expect(logic.values.sourceLoadingStates).toEqual([])
        })

        it('does not create store when feature flag is not set', () => {
            featureFlagLogic.mount()
            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.REPLAY_SNAPSHOT_STORE]: 'control',
            })
            logic = snapshotDataLogic({
                sessionRecordingId: 'no-store-test',
                blobV2PollingDisabled: true,
            })
            logic.mount()

            expect(logic.values.snapshotStore).toBeNull()
        })

        it('returns stable empty object for snapshotsBySources', () => {
            mountWithStoreFlag()

            const first = logic.values.snapshotsBySources
            const second = logic.values.snapshotsBySources
            expect(first).toBe(second)
            expect(first).toEqual({})
        })
    })

    describe('loadSnapshotSourcesSuccess', () => {
        it('populates store with sources and triggers loading', async () => {
            mountWithStoreFlag()

            await expectLogic(logic, () => {
                logic.actions.loadSnapshots()
            }).toDispatchActions(['loadSnapshotSourcesSuccess', 'resetPollingInterval', 'loadNextSnapshotSource'])

            expect(logic.values.snapshotStore!.sourceCount).toBe(3)
            expect(logic.values.sourceLoadingStates).toHaveLength(3)
        })

        it('doubles polling interval when sources are unchanged on second fetch', async () => {
            mountWithStoreFlag()

            await expectLogic(logic, () => {
                logic.actions.loadSnapshots()
            })
                .toDispatchActions(['loadSnapshotSourcesSuccess'])
                .toFinishAllListeners()

            expect(logic.values.pollingInterval).toBe(10000)

            await expectLogic(logic, () => {
                logic.actions.loadSnapshotSources()
            })
                .toDispatchActions([
                    'loadSnapshotSourcesSuccess',
                    (action) =>
                        action.type === logic.actionTypes.setPollingInterval && action.payload.intervalMs === 20000,
                ])
                .toFinishAllListeners()
        })
    })

    describe('loadSnapshotsForSourceSuccess (snapshot bucketing)', () => {
        it('buckets snapshots into store by source timestamp range', async () => {
            mountWithStoreFlag()

            await expectLogic(logic, () => {
                logic.actions.loadSnapshots()
            })
                .toDispatchActions(['loadSnapshotsForSourceSuccess'])
                .toFinishAllListeners()

            const store = logic.values.snapshotStore!
            const allSnaps = store.getAllLoadedSnapshots()
            expect(allSnaps.length).toBeGreaterThan(0)
        })

        it('marks sources as loaded after bucketing', async () => {
            mountWithStoreFlag()

            await expectLogic(logic, () => {
                logic.actions.loadSnapshots()
            })
                .toDispatchActions(['loadSnapshotsForSourceSuccess'])
                .toFinishAllListeners()

            const states = logic.values.sourceLoadingStates
            expect(states.some((s) => s.state === 'loaded')).toBe(true)
        })
    })

    describe('setTargetTimestamp', () => {
        it('triggers seek mode for unloaded data', async () => {
            mountWithStoreFlag()

            // Load sources but don't wait for full data load
            logic.actions.loadSnapshotSourcesSuccess([SOURCE_A, SOURCE_B, SOURCE_C])
            await expectLogic(logic).toFinishAllListeners()

            // Manually set sources on store without loading data
            logic.values.snapshotStore!.setSources([SOURCE_A, SOURCE_B, SOURCE_C])

            // Seek to a timestamp where data is NOT loaded
            logic.actions.setTargetTimestamp(tsMs(2))
            await expectLogic(logic).toDispatchActions(['loadNextSnapshotSource'])
        })

        it('skips seek when can already play at target', async () => {
            mountWithStoreFlag()

            logic.actions.loadSnapshotSourcesSuccess([SOURCE_A])
            await expectLogic(logic).toFinishAllListeners()

            const store = logic.values.snapshotStore!
            store.setSources([SOURCE_A])
            store.markLoaded(0, [makeFullSnapshot(tsMs(0, 0)), makeSnapshot(tsMs(0, 30))])

            await expectLogic(logic, () => {
                logic.actions.setTargetTimestamp(tsMs(0, 15))
            }).toDispatchActions(['loadNextSnapshotSource'])

            // Should NOT be in seek mode — data is already available
            expect(logic.values.isWaitingForPlayableFullSnapshot).toBe(false)
        })

        it('does not enter seek for source 0 when already in buffer_ahead', async () => {
            mountWithStoreFlag()

            logic.actions.loadSnapshotSourcesSuccess([SOURCE_A, SOURCE_B])
            await expectLogic(logic).toFinishAllListeners()

            logic.values.snapshotStore!.setSources([SOURCE_A, SOURCE_B])

            await expectLogic(logic, () => {
                logic.actions.setTargetTimestamp(tsMs(0, 0))
            }).toDispatchActions(['loadNextSnapshotSource'])

            expect(logic.values.isWaitingForPlayableFullSnapshot).toBe(false)
        })
    })

    describe('updatePlaybackPosition', () => {
        it('triggers buffer-ahead loading', async () => {
            mountWithStoreFlag()

            logic.actions.loadSnapshotSourcesSuccess([SOURCE_A, SOURCE_B])
            await expectLogic(logic).toFinishAllListeners()

            logic.values.snapshotStore!.setSources([SOURCE_A, SOURCE_B])

            await expectLogic(logic, () => {
                logic.actions.updatePlaybackPosition(tsMs(0))
            }).toDispatchActions(['loadNextSnapshotSource'])
        })

        it('is a no-op when store is not enabled', async () => {
            // Mount without store flag
            featureFlagLogic.mount()
            featureFlagLogic.actions.setFeatureFlags([], {})
            logic = snapshotDataLogic({
                sessionRecordingId: 'no-store-update-test',
                blobV2PollingDisabled: true,
            })
            logic.mount()

            expect(logic.values.snapshotStore).toBeNull()

            logic.actions.updatePlaybackPosition(tsMs(0))
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.snapshotStore).toBeNull()
            expect(logic.values.snapshotsForSourceLoading).toBe(false)
        })
    })

    describe('setPlayerActive', () => {
        it('triggers loading when activated with store', async () => {
            mountWithStoreFlag()

            logic.actions.loadSnapshotSourcesSuccess([SOURCE_A])
            await expectLogic(logic).toFinishAllListeners()

            logic.values.snapshotStore!.setSources([SOURCE_A])
            logic.actions.setPlayerActive(false)

            await expectLogic(logic, () => {
                logic.actions.setPlayerActive(true)
            }).toDispatchActions(['loadNextSnapshotSource'])
        })
    })

    describe('loadNextSnapshotSource (store path)', () => {
        it('uses scheduler to determine next batch', async () => {
            mountWithStoreFlag()

            logic.actions.loadSnapshotSourcesSuccess([SOURCE_A, SOURCE_B, SOURCE_C])
            await expectLogic(logic).toFinishAllListeners()

            logic.values.snapshotStore!.setSources([SOURCE_A, SOURCE_B, SOURCE_C])

            await expectLogic(logic, () => {
                logic.actions.loadNextSnapshotSource()
            }).toDispatchActions([
                (action) =>
                    action.type === logic.actionTypes.loadSnapshotsForSource &&
                    action.payload.sources?.length > 0 &&
                    action.payload.sources[0].blob_key === 'a',
            ])
        })

        it('starts polling when all sources are loaded', async () => {
            mountWithStoreFlag()

            logic.actions.loadSnapshotSourcesSuccess([SOURCE_A])
            await expectLogic(logic).toFinishAllListeners()

            const store = logic.values.snapshotStore!
            store.setSources([SOURCE_A])
            store.markLoaded(0, [makeFullSnapshot(tsMs(0, 0))])

            await expectLogic(logic, () => {
                logic.actions.loadNextSnapshotSource()
            }).toDispatchActions(['maybeStartPolling'])
        })
    })

    describe('selectors', () => {
        describe('snapshotsLoading', () => {
            it('is false when store has snapshots loaded', async () => {
                mountWithStoreFlag()

                const store = logic.values.snapshotStore!
                store.setSources([SOURCE_A])
                store.markLoaded(0, [makeFullSnapshot(tsMs(0, 0))])

                expect(logic.values.snapshotsLoading).toBe(false)
            })
        })

        describe('allSourcesLoaded', () => {
            it('is false before sources are set', () => {
                mountWithStoreFlag()
                expect(logic.values.allSourcesLoaded).toBe(false)
            })

            it('becomes true once all sources have been marked loaded', () => {
                mountWithStoreFlag()

                const store = logic.values.snapshotStore!
                store.setSources([SOURCE_A, SOURCE_B])

                // Trigger selector re-evaluation with a source set
                logic.actions.loadSnapshotSourcesSuccess([SOURCE_A, SOURCE_B])

                // Not yet — no data loaded
                store.markLoaded(0, [makeFullSnapshot(tsMs(0, 0))])
                logic.actions.loadSnapshotsForSourceSuccess({ sources: [SOURCE_A] })
                expect(logic.values.allSourcesLoaded).toBe(false)

                // Now mark the second source
                store.markLoaded(1, [makeSnapshot(tsMs(1, 0))])
                logic.actions.loadSnapshotsForSourceSuccess({ sources: [SOURCE_B] })
                expect(logic.values.allSourcesLoaded).toBe(true)
            })
        })

        describe('isWaitingForPlayableFullSnapshot', () => {
            it('is false when not in store mode', () => {
                featureFlagLogic.mount()
                logic = snapshotDataLogic({
                    sessionRecordingId: 'no-store-wait-test',
                    blobV2PollingDisabled: true,
                })
                logic.mount()

                expect(logic.values.isWaitingForPlayableFullSnapshot).toBe(false)
            })

            it('is false when not seeking', () => {
                mountWithStoreFlag()
                expect(logic.values.isWaitingForPlayableFullSnapshot).toBe(false)
            })
        })

        describe('storeVersion', () => {
            it('increments when store mutates', () => {
                mountWithStoreFlag()

                const initialVersion = logic.values.storeVersion
                const store = logic.values.snapshotStore!
                store.setSources([SOURCE_A])
                // storeVersion is a selector driven by snapshotsBySourceSuccessCount,
                // so we need to trigger re-evaluation
                logic.actions.loadSnapshotsForSourceSuccess({ sources: [SOURCE_A] })

                expect(logic.values.storeVersion).toBeGreaterThan(initialVersion)
            })
        })

        describe('sourceLoadingStates', () => {
            it('returns source states from store', () => {
                mountWithStoreFlag()

                const store = logic.values.snapshotStore!
                store.setSources([SOURCE_A, SOURCE_B])

                // Trigger re-evaluation
                logic.actions.loadSnapshotsForSourceSuccess({ sources: [SOURCE_A] })

                const states = logic.values.sourceLoadingStates
                expect(states).toHaveLength(2)
                expect(states[0].state).toBe('unloaded')
                expect(states[1].state).toBe('unloaded')
            })
        })
    })

    describe('full loading pipeline', () => {
        it('loads sources, fetches snapshots, and buckets them into the store', async () => {
            mountWithStoreFlag()

            await expectLogic(logic, () => {
                logic.actions.loadSnapshots()
            })
                .toDispatchActions([
                    'loadSnapshots',
                    'loadSnapshotSources',
                    'loadSnapshotSourcesSuccess',
                    // Store path: loadNextSnapshotSource gets scheduler batch
                    'loadNextSnapshotSource',
                    'loadSnapshotsForSource',
                    'loadSnapshotsForSourceSuccess',
                ])
                .toFinishAllListeners()

            const store = logic.values.snapshotStore!
            expect(store.sourceCount).toBe(3)
            expect(store.getAllLoadedSnapshots().length).toBeGreaterThan(0)
        })
    })

    describe('setSnapshots (file playback)', () => {
        it('populates store with file snapshots', async () => {
            mountWithStoreFlag()

            const fileSnapshots = [makeFullSnapshot(tsMs(0, 0)), makeSnapshot(tsMs(0, 15)), makeSnapshot(tsMs(0, 30))]

            await expectLogic(logic, () => {
                logic.actions.setSnapshots(fileSnapshots)
            })
                .toDispatchActions(['loadSnapshotSourcesSuccess', 'loadSnapshotsForSourceSuccess'])
                .toFinishAllListeners()

            const store = logic.values.snapshotStore!
            expect(store.sourceCount).toBe(1)
            expect(store.allLoaded).toBe(true)
            expect(store.getAllLoadedSnapshots()).toHaveLength(3)
        })

        it('makes snapshots available via coordinator selector', async () => {
            mountWithStoreFlag()

            const fileSnapshots = [makeFullSnapshot(tsMs(0, 0)), makeSnapshot(tsMs(0, 30))]

            await expectLogic(logic, () => {
                logic.actions.setSnapshots(fileSnapshots)
            })
                .toDispatchActions(['loadSnapshotsForSourceSuccess'])
                .toFinishAllListeners()

            const store = logic.values.snapshotStore!
            const loaded = store.getAllLoadedSnapshots()
            expect(loaded).toHaveLength(2)
            expect(loaded[0].type).toBe(EventType.FullSnapshot)
        })
    })
})
