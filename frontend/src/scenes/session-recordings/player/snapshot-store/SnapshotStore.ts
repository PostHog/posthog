import { EventType, eventWithTime } from '@posthog/rrweb-types'

import { RecordingSnapshot, SessionRecordingSnapshotSource } from '~/types'

import { SourceEntry, SourceLoadingState } from './types'

export class SnapshotStore {
    private entries: SourceEntry[] = []
    private _version = 0
    private mergedSnapshotsCache: RecordingSnapshot[] | null = null
    private snapshotsByWindowIdCache: Record<number, eventWithTime[]> | null = null

    get version(): number {
        return this._version
    }

    setSources(sources: SessionRecordingSnapshotSource[]): void {
        const existingByKey = new Map<string, SourceEntry>()
        for (const entry of this.entries) {
            if (entry.source.blob_key) {
                existingByKey.set(entry.source.blob_key, entry)
            }
        }

        this.entries = sources.map((source, index) => {
            const existing = source.blob_key ? existingByKey.get(source.blob_key) : undefined
            if (existing) {
                existing.index = index
                return existing
            }
            return {
                source,
                index,
                state: 'unloaded' as const,
                processedSnapshots: null,
                fullSnapshotTimestamps: [],
                metaTimestamps: [],
                startMs: source.start_timestamp ? new Date(source.start_timestamp).getTime() : 0,
                endMs: source.end_timestamp ? new Date(source.end_timestamp).getTime() : 0,
            }
        })
        this.bump()
    }

    get sourceCount(): number {
        return this.entries.length
    }

    get allLoaded(): boolean {
        return this.entries.length > 0 && this.entries.every((e) => e.state === 'loaded')
    }

    getEntry(index: number): SourceEntry | undefined {
        return this.entries[index]
    }

    markLoaded(sourceIndex: number, processedSnapshots: RecordingSnapshot[]): void {
        const entry = this.entries[sourceIndex]
        if (!entry) {
            return
        }

        processedSnapshots.sort((a, b) => a.timestamp - b.timestamp)

        const fullSnapshotTimestamps: number[] = []
        const metaTimestamps: number[] = []
        for (const snap of processedSnapshots) {
            if (snap.type === EventType.FullSnapshot) {
                fullSnapshotTimestamps.push(snap.timestamp)
            }
            if (snap.type === EventType.Meta) {
                metaTimestamps.push(snap.timestamp)
            }
        }

        entry.state = 'loaded'
        entry.processedSnapshots = processedSnapshots
        entry.fullSnapshotTimestamps = fullSnapshotTimestamps
        entry.metaTimestamps = metaTimestamps
        this.bump()
    }

    getAllLoadedSnapshots(): RecordingSnapshot[] {
        if (this.mergedSnapshotsCache) {
            return this.mergedSnapshotsCache
        }

        const result: RecordingSnapshot[] = []
        for (const entry of this.entries) {
            if (entry.state === 'loaded' && entry.processedSnapshots) {
                for (const snap of entry.processedSnapshots) {
                    result.push(snap)
                }
            }
        }
        this.mergedSnapshotsCache = result
        return result
    }

    getSnapshotsByWindowId(): Record<number, eventWithTime[]> {
        if (this.snapshotsByWindowIdCache) {
            return this.snapshotsByWindowIdCache
        }

        const snapshots = this.getAllLoadedSnapshots()

        const result: Record<number, eventWithTime[]> = {}
        for (const snapshot of snapshots) {
            const windowId = (snapshot as RecordingSnapshot).windowId
            if (!(windowId in result)) {
                result[windowId] = []
            }
            result[windowId].push(snapshot)
        }
        this.snapshotsByWindowIdCache = result
        return result
    }

    getSourceIndexForTimestamp(ts: number): number {
        for (let i = 0; i < this.entries.length; i++) {
            const entry = this.entries[i]
            if (ts >= entry.startMs && ts <= entry.endMs) {
                return i
            }
            if (ts < entry.startMs) {
                return Math.max(0, i - 1)
            }
        }
        return Math.max(0, this.entries.length - 1)
    }

    canPlayAt(ts: number): boolean {
        if (this.entries.length === 0) {
            return false
        }
        // Timestamp is beyond all known source data — can't play yet
        if (ts > this.entries[this.entries.length - 1].endMs) {
            return false
        }

        const fullSnapshotInfo = this.findNearestFullSnapshot(ts)
        if (!fullSnapshotInfo) {
            return false
        }

        const targetIndex = this.getSourceIndexForTimestamp(ts)

        for (let i = fullSnapshotInfo.sourceIndex; i <= targetIndex; i++) {
            if (this.entries[i]?.state !== 'loaded') {
                return false
            }
        }
        return true
    }

    findNearestFullSnapshot(ts: number): { sourceIndex: number; timestamp: number } | null {
        let bestTs = -1
        let bestSourceIndex = -1

        for (const entry of this.entries) {
            for (const fullTs of entry.fullSnapshotTimestamps) {
                if (fullTs <= ts && fullTs > bestTs) {
                    bestTs = fullTs
                    bestSourceIndex = entry.index
                }
            }
        }

        if (bestSourceIndex === -1) {
            return null
        }
        return { sourceIndex: bestSourceIndex, timestamp: bestTs }
    }

    getUnloadedIndicesInRange(start: number, end: number): number[] {
        const result: number[] = []
        const clampedStart = Math.max(0, start)
        const clampedEnd = Math.min(this.entries.length - 1, end)
        for (let i = clampedStart; i <= clampedEnd; i++) {
            if (this.entries[i]?.state !== 'loaded') {
                result.push(i)
            }
        }
        return result
    }

    getSourceStates(): SourceLoadingState[] {
        return this.entries.map((e) => ({ startMs: e.startMs, endMs: e.endMs, state: e.state }))
    }

    private bump(): void {
        this._version++
        this.mergedSnapshotsCache = null
        this.snapshotsByWindowIdCache = null
    }
}
