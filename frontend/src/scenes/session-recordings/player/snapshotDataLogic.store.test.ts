import { api } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { EventType } from '@posthog/rrweb-types'

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

    function mountLogic(): void {
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
    })

    describe('initialization', () => {
        it('creates store and scheduler when feature flag is set', () => {
            mountLogic()

            expect(logic.values.snapshotStore).not.toBeNull()
            expect(logic.values.storeVersion).toBe(0)
            expect(logic.values.sourceLoadingStates).toEqual([])
        })
    })

    describe('loadSnapshotSourcesSuccess', () => {
        it('populates store with sources and triggers loading', async () => {
            mountLogic()

            await expectLogic(logic, () => {
                logic.actions.loadSnapshots()
            }).toDispatchActions(['loadSnapshotSourcesSuccess', 'resetPollingInterval', 'loadNextSnapshotSource'])

            expect(logic.values.snapshotStore!.sourceCount).toBe(3)
            expect(logic.values.sourceLoadingStates).toHaveLength(3)
        })

        it('doubles polling interval when sources are unchanged on second fetch', async () => {
            mountLogic()

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
            mountLogic()

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
            mountLogic()

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
            mountLogic()

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
            mountLogic()

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

        it('does not override load_all mode', async () => {
            mountLogic()

            logic.actions.loadSnapshotSourcesSuccess([SOURCE_A, SOURCE_B, SOURCE_C])
            await expectLogic(logic).toFinishAllListeners()

            logic.values.snapshotStore!.setSources([SOURCE_A, SOURCE_B, SOURCE_C])

            // Enter load_all mode (as export would)
            logic.actions.loadAllSources()
            await expectLogic(logic).toFinishAllListeners()

            // Attempt to seek to unloaded data — should NOT demote to seek mode
            logic.actions.setTargetTimestamp(tsMs(2))
            await expectLogic(logic).toDispatchActions(['loadNextSnapshotSource'])

            expect(logic.values.isWaitingForPlayableFullSnapshot).toBe(false)
        })

        it('does not enter seek for source 0 when already in buffer_ahead', async () => {
            mountLogic()

            logic.actions.loadSnapshotSourcesSuccess([SOURCE_A, SOURCE_B])
            await expectLogic(logic).toFinishAllListeners()

            logic.values.snapshotStore!.setSources([SOURCE_A, SOURCE_B])

            await expectLogic(logic, () => {
                logic.actions.setTargetTimestamp(tsMs(0, 0))
            }).toDispatchActions(['loadNextSnapshotSource'])

            expect(logic.values.isWaitingForPlayableFullSnapshot).toBe(false)
        })

        it('re-evaluates isWaitingForPlayableFullSnapshot after silent seek clear (#53893 Bug B)', async () => {
            // Regression test for the stale-selector half of #53893.
            //
            // When LoadingScheduler.getSeekBatch silently clears seek mode
            // (step 5: backward search exhausted, no full snapshot found),
            // it mutates cache.scheduler.currentMode directly. The store's
            // version doesn't bump because no data is added. Without the
            // storeUpdated dispatch on that transition and a selector
            // dependency that tracks it, isWaitingForPlayableFullSnapshot
            // stays cached at `true` — poisoning the next seekToTimestamp.
            //
            // This exercise uses the step-5 path specifically because it's
            // the case where mode changes WITHOUT any store mutation, so
            // we can isolate the selector-reactivity half of the fix from
            // the step-2 path (where markLoaded would also bump the
            // selector's storeVersion dependency and mask a regression).
            mountLogic()

            // Pre-load sources as loaded-but-empty. state='loaded' means
            // no seek batch will try to load them, and empty snapshots mean
            // no full snapshot exists anywhere → canPlayAt is always false
            // and the backward search in getSeekBatch step 4/5 will exhaust.
            const store = logic.values.snapshotStore!
            store.setSources([SOURCE_A, SOURCE_B])
            store.markLoaded(0, [])
            store.markLoaded(1, [])

            // Tell Kea about the sources. setSources preserves loaded
            // entries by blob_key, and loadNextSnapshotSource sees
            // everything as loaded → no loader dispatches.
            logic.actions.loadSnapshotSourcesSuccess([SOURCE_A, SOURCE_B])
            await expectLogic(logic).toFinishAllListeners()

            // Directly put the scheduler in seek mode. setTargetTimestamp
            // would work too, but it's fiddly to arrange the early-return
            // checks in this state — direct seekTo is cleaner.
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const scheduler = (logic as any).cache.scheduler as {
                seekTo: (ts: number) => void
                currentMode: { kind: string }
            }
            scheduler.seekTo(tsMs(0, 30))

            // Pre-read: seek mode + no full snapshot → true, CACHED.
            expect(logic.values.isWaitingForPlayableFullSnapshot).toBe(true)

            // Trigger getSeekBatch. Step 1 finds nothing unloaded (all
            // loaded), step 2 canPlayAt=false (no full snapshot), step 3
            // findNearestFullSnapshot=null, step 4 backward search has
            // nothing unloaded, step 5 exhausted → clearSeek. Mode flips
            // to buffer_ahead WITHOUT any store mutation — this is the
            // isolation point that catches Bug B.
            logic.actions.loadNextSnapshotSource()
            await expectLogic(logic).toFinishAllListeners()

            // Sanity: scheduler actually exited seek mode.
            expect(scheduler.currentMode.kind).toBe('buffer_ahead')

            // Without the fix (no storeUpdated dispatch on silent clearSeek,
            // or selector depending on storeVersion instead of storeUpdateCount),
            // this returns a stale `true` because nothing in Kea's
            // reactivity graph changed while the mode flipped.
            expect(logic.values.isWaitingForPlayableFullSnapshot).toBe(false)
        })

        it('enters seek mode when called before sources load (past-end URL regression #53893)', async () => {
            // Regression test for the stuck-buffer follow-up to #53686, fixed in #53893.
            //
            // Scenario: a user opens a replay with a ?t=<past-end> URL.
            // The player dispatches setTargetTimestamp before the async
            // snapshot source list has resolved, so the store is still
            // empty at the point setTargetTimestamp runs.
            //
            // Before the fix, getSourceIndexForTimestamp returned 0 for
            // any timestamp on an empty store, tripping the "source 0 in
            // buffer_ahead" optimization and skipping scheduler.seekTo.
            // The scheduler then stayed in buffer_ahead, and once sources
            // arrived it anchored on the trailing blob (a heartbeat with
            // no full snapshot) — leaving the player stuck in BUFFER.
            mountLogic()

            // Pre-condition: store is mounted but has no sources yet.
            expect(logic.values.snapshotStore!.sourceCount).toBe(0)

            // Force memoization at false so the test catches a missing storeUpdated
            // after scheduler.seekTo (per review feedback on #53893).
            expect(logic.values.isWaitingForPlayableFullSnapshot).toBe(false)

            logic.actions.setTargetTimestamp(tsMs(5, 0))
            await expectLogic(logic).toFinishAllListeners()

            // With the fix: getSourceIndexForTimestamp returns null for
            // the empty store, so targetIndex === 0 is false and the
            // optimization doesn't fire. scheduler.seekTo runs and the
            // storeUpdated dispatch on the wasSeeking transition ensures
            // the selector re-evaluates. canPlayAt is false (no data),
            // so isWaitingForPlayableFullSnapshot is true.
            //
            // Without the fix: scheduler stays in buffer_ahead, selector
            // returns false, player has no signal to keep buffering.
            expect(logic.values.isWaitingForPlayableFullSnapshot).toBe(true)
        })
    })

    describe('updatePlaybackPosition', () => {
        it('triggers buffer-ahead loading', async () => {
            mountLogic()

            logic.actions.loadSnapshotSourcesSuccess([SOURCE_A, SOURCE_B])
            await expectLogic(logic).toFinishAllListeners()

            logic.values.snapshotStore!.setSources([SOURCE_A, SOURCE_B])

            await expectLogic(logic, () => {
                logic.actions.updatePlaybackPosition(tsMs(0))
            }).toDispatchActions(['loadNextSnapshotSource'])
        })
    })

    describe('loadAllSources', () => {
        it('switches scheduler to load_all mode and kicks off loading', async () => {
            mountLogic()

            logic.actions.loadSnapshotSourcesSuccess([SOURCE_A, SOURCE_B, SOURCE_C])
            await expectLogic(logic).toFinishAllListeners()

            logic.values.snapshotStore!.setSources([SOURCE_A, SOURCE_B, SOURCE_C])

            await expectLogic(logic, () => {
                logic.actions.loadAllSources()
            }).toDispatchActions(['loadNextSnapshotSource'])
        })
    })

    describe('setPlayerActive', () => {
        it('triggers loading when activated with store', async () => {
            mountLogic()

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
            mountLogic()

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
            mountLogic()

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
                mountLogic()

                const store = logic.values.snapshotStore!
                store.setSources([SOURCE_A])
                store.markLoaded(0, [makeFullSnapshot(tsMs(0, 0))])

                expect(logic.values.snapshotsLoading).toBe(false)
            })
        })

        describe('allSourcesLoaded', () => {
            it('is false before sources are set', () => {
                mountLogic()
                expect(logic.values.allSourcesLoaded).toBe(false)
            })

            it('becomes true once all sources have been marked loaded', () => {
                mountLogic()

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
            it('is false when not seeking', () => {
                mountLogic()
                expect(logic.values.isWaitingForPlayableFullSnapshot).toBe(false)
            })
        })

        describe('storeVersion', () => {
            it('increments when store mutates', () => {
                mountLogic()

                const initialVersion = logic.values.storeVersion
                const store = logic.values.snapshotStore!
                store.setSources([SOURCE_A])
                logic.actions.storeUpdated()

                expect(logic.values.storeVersion).toBeGreaterThan(initialVersion)
            })
        })

        describe('sourceLoadingStates', () => {
            it('returns source states from store', () => {
                mountLogic()

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
            mountLogic()

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
            mountLogic()

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
            mountLogic()

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
