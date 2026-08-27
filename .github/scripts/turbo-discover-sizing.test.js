// Run with: node --test .github/scripts/turbo-discover-sizing.test.js
//
// Unit tests for how turbo-discover.js sizes Django segments. Sharding reads
// raw sums, so an unpruned or unscoped input inflates the shard count with no
// symptom other than fast green shards. These tests pin both guards.

const test = require('node:test')
const assert = require('node:assert/strict')

const { pruneDeadDurations, getSegmentDuration, calculateShards, resolveProductSizing, buildMatrix, PRODUCT_JOB_OVERHEAD_SECONDS, PRODUCT_SAFETY_FACTOR, TARGET_WALL_SECONDS } = require('./turbo-discover.js')

// A path that exists in every checkout, so the existence check is deterministic.
const LIVE_FILE = '.github/scripts/turbo-discover.js'
const DEAD_FILE = 'posthog/test/test_file_that_was_deleted.py'

test('pruneDeadDurations drops entries whose file is gone from disk', () => {
    const pruned = pruneDeadDurations({
        [`${LIVE_FILE}::test_kept`]: 10,
        [`${DEAD_FILE}::test_removed`]: 900,
        [`${DEAD_FILE}::test_renamed_away`]: 100,
    })

    assert.deepEqual(Object.keys(pruned), [`${LIVE_FILE}::test_kept`])
})

test('pruneDeadDurations passes through a null input', () => {
    assert.equal(pruneDeadDurations(null), null)
})

// The union keeps a segment's prefix match even when a different segment ran
// the test, so the JUnit allowlist is what stops the double count.
const UNION = { 'posthog/test/test_a.py::test_a': 100, 'posthog/test/test_b.py::test_b': 900 }

test('getSegmentDuration counts only node ids the segment actually ran', () => {
    const ran = new Set(['posthog/test/test_a.py::test_a'])

    assert.equal(getSegmentDuration('Core', UNION, ran), 100)
})

test('getSegmentDuration sums the whole union when no allowlist was restored', () => {
    assert.equal(getSegmentDuration('Core', UNION, null), 1000)
})

test('getSegmentDuration still applies the segment exclude rules under an allowlist', () => {
    const union = { 'posthog/temporal/test_w.py::test_w': 50, 'posthog/test/test_a.py::test_a': 100 }
    const ran = new Set(Object.keys(union))

    // posthog/temporal/ is excluded from Core even though JUnit recorded it.
    assert.equal(getSegmentDuration('Core', union, ran), 100)
})

// Sizing to the shared flat wall target: every shard carries
// (target - overhead) of work, so walls land near the target in every lane.
test('calculateShards sizes shards to the flat wall target', () => {
    // 105 min of work, 5 min overhead: each shard gets 7 min of tests,
    // walls land at the 12 min target.
    assert.equal(calculateShards(6300, 300, 1), 15)
})

test('calculateShards rounds up, so the target is a ceiling, not an average', () => {
    assert.equal(calculateShards(6301, 300, 1), 16)
})

test('calculateShards keeps the floor and ceiling', () => {
    assert.equal(calculateShards(1, 600), 3)
    assert.equal(calculateShards(100000, 300, 1), 50)
})

test('calculateShards floors the work budget at half the overhead', () => {
    // Overhead above the target makes it unreachable; the work budget floors at
    // half the overhead instead of going negative.
    assert.equal(calculateShards(6000, TARGET_WALL_SECONDS + 100, 1), Math.ceil(6000 / ((TARGET_WALL_SECONDS + 100) / 2)))
})

// Product sizing: with the junit-scaled marker the union's product sums are
// measured magnitudes; without it they are call-only undercounts and the
// file-count staleness guard may override them.

const O = PRODUCT_JOB_OVERHEAD_SECONDS

test('resolveProductSizing trusts scaled sums and skips the file-count guess', () => {
    const union = { 'products/big_one/backend/test_a.py::test_a': 900 }

    const sizing = resolveProductSizing('big-one', union, true)

    assert.equal(sizing.work, 900)
    assert.equal(sizing.staleUnionWork, null)
})

test('buildMatrix splits a product to the shared wall target', () => {
    const union = {}
    for (let i = 0; i < 40; i++) {
        union[`products/big_one/backend/test_${i}.py::test_${i}`] = 50
    }

    const matrix = buildMatrix(['big-one'], union, true)

    // 2000s of work, with the safety factor, over a (target - overhead) budget per shard.
    assert.equal(matrix.length, Math.ceil((2000 * PRODUCT_SAFETY_FACTOR) / (TARGET_WALL_SECONDS - O)))
    assert.match(matrix[0].group, /^big-one \(1\/\d+\)$/)
})

test('buildMatrix leaves a small product packed', () => {
    const union = { 'products/small_one/backend/test_c.py::test_c': 100 }

    const matrix = buildMatrix(['small-one'], union, true)

    assert.equal(matrix.length, 1)
    assert.equal(matrix[0].group, 'small-one')
    assert.equal(matrix[0].pytest_args, '')
})
