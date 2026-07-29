import { RecordingSnapshot } from '../types'

// Monotonic across every parse in the page session, so a snapshot's seq always orders it against
// any other parsed snapshot regardless of which blob or load pass it arrived on.
let ingestSequence = 0

export const nextIngestSequence = (): number => ingestSequence++

/**
 * Orders snapshots for playback: by timestamp, then by capture order for events sharing a
 * millisecond. Without the tiebreaker, same-millisecond ordering falls out of however the array
 * happened to be built, and reordered mutations make rrweb apply text to the wrong nodes.
 */
export function sortSnapshots(snapshots: RecordingSnapshot[]): RecordingSnapshot[] {
    return snapshots
        .map((snapshot, index) => ({ snapshot, index }))
        .sort(
            (a, b) =>
                a.snapshot.timestamp - b.snapshot.timestamp ||
                compareSeq(a.snapshot.seq, b.snapshot.seq) ||
                a.index - b.index
        )
        .map(({ snapshot }) => snapshot)
}

// Snapshots synthesized during processing (patched meta, minimal full snapshots) carry no seq, and
// they are inserted next to the snapshot they were derived from, so fall through to insertion order.
function compareSeq(a: number | undefined, b: number | undefined): number {
    return a === undefined || b === undefined ? 0 : a - b
}
