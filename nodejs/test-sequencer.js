const Sequencer = require('@jest/test-sequencer').default
const path = require('path')
const fs = require('fs')

// Timing-based shard balancing.
//
// Jest's default sequencer assigns tests to shards by hashing file paths, which balances the
// *count* of files per shard but not their runtime. A handful of integration suites dominate
// (ingestion-e2e at ~138s, workflows-e2e at ~102s, hog-transformer at ~96s) and the hash
// decides which shard they land in, so the slowest shard drifts further from the mean the more
// shards you add — the whole job waits on that one.
//
// This sequencer reads a timing manifest and uses greedy bin-packing to distribute tests evenly.
// Falls back to default behavior when no manifest exists (first run, new test files, etc).

const TIMINGS_PATH = path.join(__dirname, 'nodejs-timings.json')

function loadTimings() {
    try {
        // eslint-disable-next-line no-restricted-syntax -- Jest loads this config module before any src/ transform
        return JSON.parse(fs.readFileSync(TIMINGS_PATH, 'utf8'))
    } catch {
        return null
    }
}

function getRelativePath(test) {
    return path.posix.relative(
        test.context.config.rootDir.split(path.sep).join(path.posix.sep),
        test.path.split(path.sep).join(path.posix.sep)
    )
}

function lightestShard(shardTotals) {
    let lightest = 0
    for (let i = 1; i < shardTotals.length; i++) {
        if (shardTotals[i] < shardTotals[lightest]) {
            lightest = i
        }
    }
    return lightest
}

// Greedy bin-packing: assign each test (longest first) to the lightest shard.
// Tests without timing data go into a separate pool and are spread evenly
// after the known tests are placed.
function binPackShard(tests, shardCount, shardIndex, timings) {
    // Canonical path order upfront — makes the entire partition deterministic
    // regardless of readdir order on the CI runner's filesystem.
    const sorted = [...tests].sort((a, b) => {
        const pa = getRelativePath(a)
        const pb = getRelativePath(b)
        return pa < pb ? -1 : pa > pb ? 1 : 0
    })

    const known = []
    const unknown = []

    for (const test of sorted) {
        const duration = timings[getRelativePath(test)]
        if (typeof duration === 'number') {
            known.push({ test, duration })
        } else {
            unknown.push(test)
        }
    }

    // Sort known tests longest-first. Stable sort preserves path order for ties.
    known.sort((a, b) => b.duration - a.duration)

    const shardTotals = new Array(shardCount).fill(0)
    const shardTests = Array.from({ length: shardCount }, () => [])

    for (const { test, duration } of known) {
        const lightest = lightestShard(shardTotals)
        shardTests[lightest].push(test)
        shardTotals[lightest] += duration
    }

    // The manifest only carries suites slow enough to matter, so the unknown pool is mostly
    // sub-second unit tests plus whatever landed since the last refresh. Charge each one the
    // median known duration — enough to keep a burst of new-and-slow files from piling onto
    // one shard, without letting hundreds of fast files distort the packing.
    const median = known.length > 0 ? known[Math.floor(known.length / 2)].duration : 10
    for (const test of unknown) {
        const lightest = lightestShard(shardTotals)
        shardTests[lightest].push(test)
        shardTotals[lightest] += median
    }

    // shardIndex is 1-based
    return shardTests[shardIndex - 1]
}

class BalancedSequencer extends Sequencer {
    /** @returns {import('@jest/test-result').Test[]} */
    shard(tests, options) {
        const timings = loadTimings()
        if (!timings) {
            // No manifest — fall back to default hash-based sharding
            return super.shard(tests, options)
        }

        return binPackShard(tests, options.shardCount, options.shardIndex, timings)
    }

    // Keep default sort() — it uses Jest's built-in perf cache for
    // within-shard ordering (failed first, then longest first).
}

module.exports = BalancedSequencer
