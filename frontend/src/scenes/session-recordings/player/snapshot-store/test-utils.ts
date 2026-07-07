import { SnapshotStore } from '@posthog/replay-shared'

import { RecordingSnapshot } from '~/types'

// One-shot fetched+processed seeding for tests that don't exercise the processing pipeline; production code must go through markFetched + markProcessed.
export function markLoaded(store: SnapshotStore, sourceIndex: number, snapshots: RecordingSnapshot[]): void {
    store.markFetched(sourceIndex, snapshots)
    store.markProcessed([sourceIndex])
}

export function allLoadedSnapshots(store: SnapshotStore): RecordingSnapshot[] {
    const result: RecordingSnapshot[] = []
    for (let i = 0; i < store.sourceCount; i++) {
        const entry = store.getEntry(i)
        if (entry?.state !== 'unloaded' && entry?.processedSnapshots) {
            result.push(...entry.processedSnapshots)
        }
    }
    return result.sort((a, b) => a.timestamp - b.timestamp)
}
