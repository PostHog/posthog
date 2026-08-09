// Run with: node --test .github/scripts/turbo-discover-sharding.test.js
//
// Unit tests for the product sharding decisions in turbo-discover.js: buildMatrix.
// Uses synthetic product names and durations throughout, and injects shard floors
// rather than reading MIN_SHARDS_BY_PRODUCT, so these never turn into
// change-detector tests that break when a product is added to or dropped from
// the floor list.

const test = require('node:test')
const assert = require('node:assert/strict')

const { buildMatrix, PRODUCT_TARGET_WALL_SECONDS } = require('./turbo-discover')

// Cheap enough that duration-based sharding would never split it, and cheap
// enough that two of them still fit one bucket.
function cheapDurations(...products) {
    const durations = {}
    for (const product of products) {
        durations[`products/${product}/backend/tests/test_thing.py::test_one`] = 5
    }
    return durations
}

function groups(matrix) {
    return matrix.map((entry) => entry.group)
}

test('a floored product splits to its floor even when its duration is far under target', () => {
    const matrix = buildMatrix(['alpha', 'beta'], cheapDurations('alpha', 'beta'), { alpha: 3 })

    assert.deepEqual(
        groups(matrix).filter((g) => g.startsWith('alpha')).sort(),
        ['alpha (1/3)', 'alpha (2/3)', 'alpha (3/3)']
    )
    // The point of the floor is fewer tests per pytest session, so the shards must
    // carry pytest-split args and must not be packed alongside another product.
    for (const entry of matrix.filter((e) => e.group.startsWith('alpha'))) {
        assert.match(entry.pytest_args, /--splits 3 --group \d --splitting-algorithm optimal_chunks/)
        assert.equal(entry.filters, '--filter=@posthog/products-alpha')
    }
    assert.ok(!groups(matrix).some((g) => g.includes(',') && g.includes('alpha')))
})

test('an unfloored product under target is still packed with its bucket-mates', () => {
    const matrix = buildMatrix(['alpha', 'beta'], cheapDurations('alpha', 'beta'), {})

    assert.deepEqual(groups(matrix), ['alpha, beta'])
})

test('duration wins when it demands more shards than the floor', () => {
    // Four times the target, so duration-based sharding asks for 4 — the floor of 2
    // must not cap it back down.
    const durations = { 'products/alpha/backend/tests/test_big.py::test_one': PRODUCT_TARGET_WALL_SECONDS * 4 }
    const matrix = buildMatrix(['alpha'], durations, { alpha: 2 })

    assert.equal(matrix.length, 5)
    assert.ok(groups(matrix).every((g) => g.endsWith('/5)')))
})
