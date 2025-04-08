import { RecordingSnapshot } from '~/types'

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

export const deduplicateSnapshots = (snapshots: RecordingSnapshot[] | null): RecordingSnapshot[] => {
    const seenHashes: Set<string> = new Set()

    return (snapshots ?? [])
        .filter((snapshot) => {
            // For a multitude of reasons, there can be duplicate snapshots in the same recording.
            // we have to stringify the snapshot to compare it to other snapshots.
            // so we can filter by storing them all in a set

            // we can see duplicates that only differ by delay - these still count as duplicates
            // even though the delay would hide that
            const { delay: _delay, ...delayFreeSnapshot } = snapshot
            // we check each item multiple times as new snapshots come in
            // so store the computer value on the object to save recalculating it so much
            const key = (snapshot as any).seen || cyrb53(JSON.stringify(delayFreeSnapshot))
            ;(snapshot as any).seen = key

            if (seenHashes.has(key)) {
                return false
            }
            seenHashes.add(key)
            return true
        })
        .sort((a, b) => a.timestamp - b.timestamp)
}
