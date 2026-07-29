import { RecordingSnapshot } from '../types'

/**
 * Indices of snapshots that ingestion wrote more than once, rather than distinct captures.
 *
 * Only events sharing a millisecond are candidates, and only in the two shapes a repeated write
 * takes: the same line twice in a row, or a whole millisecond's worth of events repeated as a block.
 * Everything else is kept, because rrweb applies mutations by node id with last write wins: an event
 * that merely repeats something seen earlier in the same millisecond is a genuine change and change
 * back, and discarding it leaves the node rendering the intermediate value instead of the final one.
 *
 * Snapshots must already be in playback order, so that equal timestamps are contiguous.
 *
 * Hashing a recording's worth of large mutations is enough work to freeze the player, so callers on
 * the main thread pass `yieldIfNeeded` to hand control back between runs.
 */
export async function findDuplicateIndices(
    snapshots: RecordingSnapshot[],
    yieldIfNeeded: () => Promise<void> = () => Promise.resolve()
): Promise<Set<number>> {
    const duplicates = new Set<number>()

    let runStart = 0
    for (let i = 1; i <= snapshots.length; i++) {
        if (i < snapshots.length && snapshots[i].timestamp === snapshots[runStart].timestamp) {
            continue
        }
        collectRunDuplicates(snapshots, runStart, i, duplicates)
        runStart = i
        await yieldIfNeeded()
    }

    return duplicates
}

function collectRunDuplicates(
    snapshots: RecordingSnapshot[],
    start: number,
    end: number,
    duplicates: Set<number>
): void {
    if (end - start < 2) {
        return
    }

    // Hashing is the expensive part of processing, so it is confined to events that share a timestamp.
    const hashes: number[] = []
    for (let i = start; i < end; i++) {
        hashes.push(hashSnapshot(snapshots[i]))
    }

    const kept: number[] = []
    for (let i = start; i < end; i++) {
        const previous = kept[kept.length - 1]
        // Chunks of one oversized mutation are near-identical by construction (see
        // chunkMutationSnapshot), and dropping one strands the last chunk's `texts` and `attributes`
        // from the nodes an earlier chunk was supposed to add.
        const repeatsPrevious = previous !== undefined && hashes[i - start] === hashes[previous - start]
        if (repeatsPrevious && !snapshots[i].isMutationChunk) {
            duplicates.add(i)
            continue
        }
        kept.push(i)
    }

    const period = repeatedBlockLength(kept.map((i) => hashes[i - start]))
    for (let i = period; i < kept.length; i++) {
        duplicates.add(kept[i])
    }
}

// Length of the shortest prefix whose exact repetition reproduces the whole sequence, or the full
// length when the sequence is not a repeated block.
function repeatedBlockLength(hashes: number[]): number {
    for (let period = 1; period <= hashes.length / 2; period++) {
        if (hashes.length % period !== 0) {
            continue
        }
        let repeats = true
        for (let i = period; i < hashes.length && repeats; i++) {
            repeats = hashes[i] === hashes[i - period]
        }
        if (repeats) {
            return period
        }
    }
    return hashes.length
}

// seq and isMutationChunk are processing bookkeeping rather than captured content, so two events that
// are genuinely the same line written twice must still hash the same. delay is added by rrweb.
function hashSnapshot(snapshot: RecordingSnapshot): number {
    const { delay, seq, isMutationChunk, ...comparableSnapshot } = snapshot
    return cyrb53(JSON.stringify(comparableSnapshot))
}

/*
    cyrb53 (c) 2018 bryc (github.com/bryc)
    License: Public domain. Attribution appreciated.
    A fast and simple 53-bit string hash function with decent collision resistance.
    Largely inspired by MurmurHash2/3, but with a focus on speed/simplicity.
*/
const cyrb53 = function (str: string, seed = 0): number {
    let h1 = 0xdeadbeef ^ seed,
        h2 = 0x41c6ce57 ^ seed
    for (let i = 0, ch; i < str.length; i++) {
        ch = str.charCodeAt(i)
        h1 = Math.imul(h1 ^ ch, 2654435761)
        h2 = Math.imul(h2 ^ ch, 1597334677)
    }
    h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507)
    h1 ^= Math.imul(h2 ^ (h2 >>> 13), 3266489909)
    h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507)
    h2 ^= Math.imul(h1 ^ (h1 >>> 13), 3266489909)
    return 4294967296 * (2097151 & h2) + (h1 >>> 0)
}
