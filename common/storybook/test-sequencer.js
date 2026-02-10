const Sequencer = require('@jest/test-sequencer').default
const path = require('path')
const fs = require('fs')

// Timing-based shard balancing.
//
// Jest's default sequencer assigns tests to shards by hashing file paths,
// which creates persistent hotspots (e.g. Max.stories.tsx at 176s lands
// with Dashboards.stories.tsx at 70s — one shard takes 577s while another
// takes 223s).
//
// This sequencer reads a timing manifest and uses greedy bin-packing to
// distribute tests evenly across shards. Falls back to default behavior
// when no manifest exists (first run, new test files, etc).

const TIMINGS_PATH = path.join(__dirname, 'storybook-timings.json')

function loadTimings() {
    try {
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

function getDuration(timings, relativePath, browser) {
    const entry = timings[relativePath]
    if (!entry) {
        return null
    }
    return entry[browser] ?? entry.chromium ?? Object.values(entry)[0] ?? null
}

// Greedy bin-packing: assign each test (longest first) to the lightest shard.
// Tests without timing data go into a separate pool and are spread evenly
// after the known tests are placed.
function binPackShard(tests, shardCount, shardIndex, timings, browser) {
    const known = []
    const unknown = []

    for (const test of tests) {
        const rel = getRelativePath(test)
        const duration = getDuration(timings, rel, browser)
        if (duration !== null) {
            known.push({ test, duration })
        } else {
            unknown.push(test)
        }
    }

    // Sort known tests longest-first
    known.sort((a, b) => b.duration - a.duration)

    const shardTotals = new Array(shardCount).fill(0)
    const shardTests = Array.from({ length: shardCount }, () => [])

    // Place known tests via greedy bin-packing
    for (const { test, duration } of known) {
        let lightest = 0
        for (let i = 1; i < shardCount; i++) {
            if (shardTotals[i] < shardTotals[lightest]) {
                lightest = i
            }
        }
        shardTests[lightest].push(test)
        shardTotals[lightest] += duration
    }

    // Spread unknown tests round-robin across shards (lightest first each time)
    for (const test of unknown) {
        let lightest = 0
        for (let i = 1; i < shardCount; i++) {
            if (shardTotals[i] < shardTotals[lightest]) {
                lightest = i
            }
        }
        shardTests[lightest].push(test)
        // Use median duration as estimate for unknown tests
        const median = known.length > 0 ? known[Math.floor(known.length / 2)].duration : 10
        shardTotals[lightest] += median
    }

    // shardIndex is 1-based
    return shardTests[shardIndex - 1]
}

class BalancedSequencer extends Sequencer {
    shard(tests, options) {
        const timings = loadTimings()
        if (!timings) {
            // No manifest — fall back to default hash-based sharding
            return super.shard(tests, options)
        }

        const browser = (process.env.TEST_BROWSERS || 'chromium').split(',')[0].trim()
        return binPackShard(tests, options.shardCount, options.shardIndex, timings, browser)
    }

    // Keep default sort() — it uses Jest's built-in perf cache for
    // within-shard ordering (failed first, then longest first).
}

module.exports = BalancedSequencer
