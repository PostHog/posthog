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

function readTagFilter(name, fallback) {
    return process.env[name] ? process.env[name].split(',').map((tag) => tag.trim()) : fallback
}

function runnableStoryFilter() {
    const included = readTagFilter('STORYBOOK_INCLUDE_TAGS', ['test'])
    const omitted = [
        ...readTagFilter('STORYBOOK_EXCLUDE_TAGS', []),
        ...readTagFilter('STORYBOOK_SKIP_TAGS', ['test-skip']),
    ]
    return (entry) =>
        entry.type === 'story' &&
        (included.length === 0 || included.some((tag) => entry.tags?.includes(tag))) &&
        !omitted.some((tag) => entry.tags?.includes(tag))
}

function loadStoryCounts() {
    try {
        const index = JSON.parse(fs.readFileSync(path.join(__dirname, 'dist/index.json'), 'utf8'))
        const isRunnable = runnableStoryFilter()
        const counts = new Map()
        for (const entry of Object.values(index.entries)) {
            if (!isRunnable(entry)) {
                continue
            }
            const file = path.resolve(__dirname, entry.importPath)
            counts.set(file, (counts.get(file) || 0) + 1)
        }
        return counts
    } catch {
        return new Map()
    }
}

function medianDuration(durations, fallback) {
    durations.sort((a, b) => b - a)
    return durations.length ? durations[Math.floor(durations.length / 2)] : fallback
}

function estimateStoryDuration(tests, timings, browser, counts) {
    const durations = []
    for (const test of tests) {
        const duration = getDuration(timings, getRelativePath(test), browser)
        const count = counts.get(test.path)
        if (duration !== null && count > 0) {
            durations.push(duration / count)
        }
    }
    return medianDuration(durations, null)
}

// Greedy bin-packing: assign each test (longest first) to the lightest shard.
// The built index lets new suites enter the same duration ordering before their first timing refresh.
function binPackShard(tests, shardCount, shardIndex, timings, browser, counts) {
    // Canonical path order upfront — makes the entire partition deterministic
    // regardless of readdir order on the CI runner's filesystem.
    const sorted = [...tests].sort((a, b) => {
        const pa = getRelativePath(a)
        const pb = getRelativePath(b)
        return pa < pb ? -1 : pa > pb ? 1 : 0
    })

    const secondsPerStory = estimateStoryDuration(sorted, timings, browser, counts)
    const fallbackDuration = medianDuration(
        sorted
            .map((test) => getDuration(timings, getRelativePath(test), browser))
            .filter((duration) => duration !== null),
        10
    )
    const known = []
    const unknown = []

    for (const test of sorted) {
        const rel = getRelativePath(test)
        const measured = getDuration(timings, rel, browser)
        const count = counts.get(test.path)
        const duration = measured ?? (secondsPerStory !== null && count > 0 ? secondsPerStory * count : null)
        if (duration !== null) {
            known.push({ test, duration })
        } else {
            unknown.push(test)
        }
    }

    // Sort known tests longest-first. Stable sort preserves path order for ties.
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
        shardTotals[lightest] += fallbackDuration
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

        const browser = (process.env.TEST_BROWSERS || 'chromium').split(',')[0].trim()
        return binPackShard(tests, options.shardCount, options.shardIndex, timings, browser, loadStoryCounts())
    }

    // Keep default sort() — it uses Jest's built-in perf cache for
    // within-shard ordering (failed first, then longest first).
}

module.exports = BalancedSequencer
