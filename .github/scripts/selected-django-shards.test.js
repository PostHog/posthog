const { test } = require('node:test')
const assert = require('node:assert')
const { execFileSync } = require('node:child_process')
const path = require('path')

const { selectedShards } = require('./selected-django-shards.js')

test('applies the full-matrix budget to the selected seconds of each segment', () => {
    // Core: ceil(5000 * 1.3 / (1200 - 240)) = 7. Temporal has the larger overhead:
    // ceil(900 * 1.3 / (1200 - 360)) = 2. POE floors at 1 despite nothing selected.
    const selection = { durations: { selected_seconds_by_segment: { core: 5000, poe: 0, temporal: 900 } } }
    assert.deepStrictEqual(selectedShards(selection), { core: 7, poe: 1, temporal: 2 })
})

test('floors at one shard, below the full-run minimum of three', () => {
    const selection = { durations: { selected_seconds_by_segment: { core: 30, poe: 30, temporal: 30 } } }
    assert.deepStrictEqual(selectedShards(selection), { core: 1, poe: 1, temporal: 1 })
})

test('caps at the full-run maximum', () => {
    const selection = { durations: { selected_seconds_by_segment: { core: 10_000_000 } } }
    assert.strictEqual(selectedShards(selection).core, 50)
})

test('degrades to one shard per segment on missing or malformed selector output', () => {
    for (const selection of [{}, { durations: {} }, { durations: { selected_seconds_by_segment: { core: 'wat' } } }]) {
        assert.deepStrictEqual(selectedShards(selection), { core: 1, poe: 1, temporal: 1 })
    }
})

test('the CLI prints the one-shard default when the selection file is unreadable', () => {
    const script = path.join(__dirname, 'selected-django-shards.js')
    const stdout = execFileSync('node', [script, '/nonexistent/selection.json'], { encoding: 'utf8' })
    assert.deepStrictEqual(JSON.parse(stdout), { core: 1, poe: 1, temporal: 1 })
})
