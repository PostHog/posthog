// Run with: node --test .github/scripts/turbo-discover-sizing.test.js
//
// Unit tests for how turbo-discover.js sizes Django segments. Sharding reads
// raw sums, so an unpruned or unscoped input inflates the shard count with no
// symptom other than fast green shards. These tests pin both guards.

const test = require('node:test')
const assert = require('node:assert/strict')

const { pruneDeadDurations, getSegmentDuration } = require('./turbo-discover.js')

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
