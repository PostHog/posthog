// Run with: node --test .github/scripts/turbo-discover-sizing.test.js
//
// Unit tests for how turbo-discover.js sizes Django segments. Sharding reads
// raw sums, so an unpruned or unscoped input inflates the shard count with no
// symptom other than fast green shards. These tests pin both guards.

const test = require('node:test')
const assert = require('node:assert/strict')

const { pruneDeadDurations, getSegmentDuration, calculateShards, resolveProductSizing, buildMatrix, PRODUCT_JOB_OVERHEAD_SECONDS } = require('./turbo-discover.js')

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

// Sizing at 50% parallel efficiency: a shard's test time equals its overhead,
// which reduces to ceil(work / overhead).
test('calculateShards sizes a segment at 50% parallel efficiency', () => {
    // 100 min of work against 10 min of overhead: 10 shards, each 10 min of tests.
    assert.equal(calculateShards(6000, 600, 1), 10)
})

test('calculateShards rounds up, so efficiency never falls below half', () => {
    assert.equal(calculateShards(6001, 600, 1), 11)
})

test('calculateShards keeps the floor and ceiling', () => {
    assert.equal(calculateShards(1, 600), 3)
    assert.equal(calculateShards(6000, 1, 1), 50)
})

test('calculateShards caps out rather than dividing by a zero overhead', () => {
    assert.equal(calculateShards(6000, 0, 1), 50)
})

// Product sizing: JUnit-calibrated {work, session} totals against the union's
// call sums. The session cost is paid per shard, so it sizes like overhead.

test('calculateShards rounds to nearest for products, so a small product stays whole', () => {
    // Work barely past one overhead: a second shard would halve efficiency.
    assert.equal(calculateShards(300, 270, 1, Math.round), 1)
})

const O = PRODUCT_JOB_OVERHEAD_SECONDS

test('resolveProductSizing prefers the setup-inclusive junit totals over the union call sum', () => {
    const union = { 'products/big_one/backend/test_a.py::test_a': 60 }
    const totals = { 'big-one': { work: 500, session: 20 } }

    const sizing = resolveProductSizing('big-one', union, totals)

    assert.equal(sizing.calibrated, true)
    assert.equal(sizing.work, 500)
    assert.equal(sizing.session, 20)
})

test('resolveProductSizing keeps the union sum when the branch moved suites into the job', () => {
    // Union records more call time than the junit total: the timing run predates
    // the change, so the junit numbers no longer describe the job.
    const union = { 'products/big_one/backend/test_a.py::test_a': 900 }
    const totals = { 'big-one': { work: 500, session: 20 } }

    const sizing = resolveProductSizing('big-one', union, totals)

    assert.equal(sizing.calibrated, false)
    assert.equal(sizing.work, 900)
})

test('buildMatrix splits a calibrated product by work over overhead plus session', () => {
    const totals = { 'big-one': { work: O * 4, session: O } }

    const matrix = buildMatrix(['big-one'], {}, totals)

    // round(4*O / (O + O)) = 2 shards, not round(4*O / O) = 4: every shard
    // re-pays the session cost, so it must count against splitting.
    assert.equal(matrix.length, 2)
    assert.match(matrix[0].group, /^big-one \(1\/2\)$/)
})

test('buildMatrix leaves a calibrated small product packed', () => {
    const totals = { 'small-one': { work: 100, session: 10 } }

    const matrix = buildMatrix(['small-one'], {}, totals)

    assert.equal(matrix.length, 1)
    assert.equal(matrix[0].group, 'small-one')
    assert.equal(matrix[0].pytest_args, '')
})

test('buildMatrix falls back to the legacy wall-target rule when the union is ahead of junit', () => {
    const union = {}
    for (let i = 0; i < 60; i++) {
        union[`products/big_one/backend/test_${i}.py::test_${i}`] = 60
    }
    const totals = { 'big-one': { work: 100, session: 10 } }

    const matrix = buildMatrix(['big-one'], union, totals)

    // 3600s of recorded call time beats the 110s junit total. Call sums undercount,
    // so the conservative legacy divisor applies: ceil((3600 + 60) / 600).
    assert.equal(matrix.length, 7)
})
