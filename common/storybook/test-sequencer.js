const Sequencer = require('@jest/test-sequencer').default

// Jest's default sequencer sorts tests alphabetically, so --shard always assigns
// the same files to the same shard. This creates persistent hotspots when heavy
// stories (e.g. dashboards) cluster together. Shuffling with a per-PR seed spreads
// them across shards while keeping reruns of the same PR deterministic.

// Simple seeded PRNG (mulberry32)
function mulberry32(seed) {
    return function () {
        seed |= 0
        seed = (seed + 0x6d2b79f5) | 0
        let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
        t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296
    }
}

// Fisher-Yates shuffle with seeded PRNG
function seededShuffle(array, seed) {
    const rng = mulberry32(seed)
    const result = [...array]
    for (let i = result.length - 1; i > 0; i--) {
        const j = Math.floor(rng() * (i + 1))
        ;[result[i], result[j]] = [result[j], result[i]]
    }
    return result
}

class ShuffledSequencer extends Sequencer {
    sort(tests) {
        const raw = process.env.STORYBOOK_SHUFFLE_SEED
        // PR number parses as base-10 int; commit SHA falls through to base-16
        const seed = raw ? parseInt(raw, 10) || parseInt(raw.slice(0, 8), 16) : Date.now()
        return seededShuffle(tests, seed)
    }
}

module.exports = ShuffledSequencer
