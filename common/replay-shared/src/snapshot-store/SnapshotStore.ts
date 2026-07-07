import { EventType } from 'posthog-js/rrweb-types'

import { RecordingSnapshot, SessionRecordingSnapshotSource } from '../types'
import { FullSnapshotRef, SourceEntry, SourceLoadingState } from './types'

export class SnapshotStore {
    private entries: SourceEntry[] = []
    private _version = 0

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
                fullSnapshots: [],
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

    // Raw data has arrived but hasn't been through snapshot processing yet — playable state ('loaded') is granted by markProcessed.
    markFetched(sourceIndex: number, snapshots: RecordingSnapshot[]): void {
        const entry = this.entries[sourceIndex]
        if (!entry) {
            return
        }

        snapshots.sort((a, b) => a.timestamp - b.timestamp)

        const fullSnapshots: FullSnapshotRef[] = []
        for (const snap of snapshots) {
            if (snap.type === EventType.FullSnapshot) {
                fullSnapshots.push({ timestamp: snap.timestamp, windowId: snap.windowId })
            }
        }

        entry.state = 'fetched'
        entry.processedSnapshots = snapshots
        entry.fullSnapshots = fullSnapshots
        this.bump()
    }

    // Flips fetched sources to loaded once a processing pass has covered them.
    markProcessed(sourceIndexes: number[]): boolean {
        let changed = false
        for (const sourceIndex of sourceIndexes) {
            const entry = this.entries[sourceIndex]
            if (entry?.state === 'fetched') {
                entry.state = 'loaded'
                changed = true
            }
        }
        if (changed) {
            this.bump()
        }
        return changed
    }

    /**
     * Returns the index of the source whose timestamp range contains `ts`,
     * or the nearest source if `ts` falls outside any range. Returns `null`
     * when the store has no sources yet — callers MUST handle this case
     * explicitly rather than conflating it with "source 0", which is a
     * valid result and hides initial-load races (see #53893).
     */
    getSourceIndexForTimestamp(ts: number): number | null {
        if (this.entries.length === 0) {
            return null
        }
        // Binary search over startMs (sources arrive time-ordered): positions inside a range resolve to it, positions in inter-source gaps or past the ends resolve to the nearest source.
        let low = 0
        let high = this.entries.length - 1
        let candidate = -1
        while (low <= high) {
            const mid = (low + high) >> 1
            if (this.entries[mid].startMs <= ts) {
                candidate = mid
                low = mid + 1
            } else {
                high = mid - 1
            }
        }
        return Math.max(0, candidate)
    }

    canPlayAt(ts: number, windowId?: number): boolean {
        if (this.entries.length === 0) {
            return false
        }

        // Positions beyond the last source resolve to it, so a fully-loaded tail can render its last frame without first fetching the whole recording.
        const fullSnapshotInfo = this.findNearestFullSnapshot(ts, windowId)
        if (!fullSnapshotInfo) {
            return false
        }

        const targetIndex = this.getSourceIndexForTimestamp(ts)
        if (targetIndex === null) {
            return false
        }

        for (let i = fullSnapshotInfo.sourceIndex; i <= targetIndex; i++) {
            if (this.entries[i]?.state !== 'loaded') {
                return false
            }
        }
        return true
    }

    /**
     * Returns the latest loaded FullSnapshot at or before `ts`, or null if none.
     * When `windowId` is given, only FullSnapshots captured in that window count —
     * rrweb renders one window at a time, so another window's FullSnapshot cannot
     * make this window's events renderable.
     */
    findNearestFullSnapshot(ts: number, windowId?: number): { sourceIndex: number; timestamp: number } | null {
        let bestTs = -1
        let bestSourceIndex = -1

        for (const entry of this.entries) {
            // entries past `ts` can't hold a FullSnapshot at or before it (refs never precede their entry's start, except entry 0's)
            if (entry.index > 0 && entry.startMs > ts) {
                break
            }
            for (const fullSnapshot of entry.fullSnapshots) {
                if (windowId !== undefined && fullSnapshot.windowId !== windowId) {
                    continue
                }
                if (fullSnapshot.timestamp <= ts && fullSnapshot.timestamp > bestTs) {
                    bestTs = fullSnapshot.timestamp
                    bestSourceIndex = entry.index
                }
            }
        }

        if (bestSourceIndex === -1) {
            return null
        }
        return { sourceIndex: bestSourceIndex, timestamp: bestTs }
    }

    // Whether every source covering [startTs, endTs] has been processed; null = unknown (no sources yet), callers keep their default.
    isRangeLoaded(startTs: number, endTs: number): boolean | null {
        if (this.entries.length === 0) {
            return null
        }
        const startIndex = this.getSourceIndexForTimestamp(startTs)
        const endIndex = this.getSourceIndexForTimestamp(endTs)
        if (startIndex === null || endIndex === null) {
            return null
        }
        return this.getUnloadedIndicesInRange(startIndex, endIndex).length === 0
    }

    // Allocation-free existence check for the load planner's recovery scan.
    hasFullSnapshotAfter(ts: number, windowId?: number): boolean {
        for (const entry of this.entries) {
            for (const fullSnapshot of entry.fullSnapshots) {
                if (fullSnapshot.timestamp >= ts && (windowId === undefined || fullSnapshot.windowId === windowId)) {
                    return true
                }
            }
        }
        return false
    }

    get hasLoadedAnySource(): boolean {
        return this.entries.some((entry) => entry.state === 'loaded')
    }

    /**
     * Returns all loaded FullSnapshots at or after `ts`, sorted by timestamp.
     * Used to recover playback when the data before `ts` has no FullSnapshot to
     * render from (e.g. the initial full snapshot was lost at capture time).
     */
    fullSnapshotsAfter(ts: number): (FullSnapshotRef & { sourceIndex: number })[] {
        const result: (FullSnapshotRef & { sourceIndex: number })[] = []
        for (const entry of this.entries) {
            for (const fullSnapshot of entry.fullSnapshots) {
                if (fullSnapshot.timestamp >= ts) {
                    result.push({ ...fullSnapshot, sourceIndex: entry.index })
                }
            }
        }
        return result.sort((a, b) => a.timestamp - b.timestamp)
    }

    syncFullSnapshotTimestamps(processedSnapshots: RecordingSnapshot[]): boolean {
        // Bucketed by nearest source (not by [startMs, endMs] range) so a synthesized FullSnapshot whose timestamp falls between two sources' metadata ranges is still indexed somewhere.
        const buckets = new Map<number, FullSnapshotRef[]>()
        for (const snap of processedSnapshots) {
            if (snap.type !== EventType.FullSnapshot) {
                continue
            }
            const sourceIndex = this.getSourceIndexForTimestamp(snap.timestamp)
            if (sourceIndex === null) {
                continue
            }
            const bucket = buckets.get(sourceIndex) ?? []
            bucket.push({ timestamp: snap.timestamp, windowId: snap.windowId })
            buckets.set(sourceIndex, bucket)
        }

        let changed = false
        for (const entry of this.entries) {
            if (entry.state !== 'loaded') {
                continue
            }
            const fullSnapshots = (buckets.get(entry.index) ?? []).sort((a, b) => a.timestamp - b.timestamp)
            if (
                fullSnapshots.length !== entry.fullSnapshots.length ||
                fullSnapshots.some(
                    (fs, j) =>
                        fs.timestamp !== entry.fullSnapshots[j].timestamp ||
                        fs.windowId !== entry.fullSnapshots[j].windowId
                )
            ) {
                entry.fullSnapshots = fullSnapshots
                changed = true
            }
        }
        if (changed) {
            this.bump()
        }
        return changed
    }

    // Deliberately does not bump(): consumers should keep their memoized view, since only loaded-state metadata stays meaningful and fetched entries keep their still-unprocessed raw data.
    clearSnapshotData(): void {
        for (const entry of this.entries) {
            if (entry.state === 'loaded') {
                entry.processedSnapshots = null
            }
        }
    }

    // "Not yet playable" — fetched-but-unprocessed sources count; use for renderability, not for planning fetches.
    getUnloadedIndicesInRange(start: number, end: number): number[] {
        return this.indicesInRange(start, end, (state) => state !== 'loaded')
    }

    // "Not yet requested" — what the load planner still needs to fetch from the network.
    getUnfetchedIndicesInRange(start: number, end: number): number[] {
        return this.indicesInRange(start, end, (state) => state === 'unloaded')
    }

    private indicesInRange(start: number, end: number, matches: (state: SourceEntry['state']) => boolean): number[] {
        const result: number[] = []
        const clampedStart = Math.max(0, start)
        const clampedEnd = Math.min(this.entries.length - 1, end)
        for (let i = clampedStart; i <= clampedEnd; i++) {
            if (matches(this.entries[i]?.state ?? 'unloaded')) {
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
    }
}
