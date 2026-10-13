// Run with: node --test .github/scripts/jest-select.test.js

const test = require('node:test')
const assert = require('node:assert/strict')

const { planShards, planOutputs, TEST_FILES_PER_SHARD, MAX_SHARDS } = require('./jest-select.js')

test('planShards adds a shard when the file limit is exceeded', () => {
    assert.equal(planShards(TEST_FILES_PER_SHARD), 1)
    assert.equal(planShards(TEST_FILES_PER_SHARD + 1), 2)
    assert.equal(planShards(2000), 6)
})

test('planShards caps the count at MAX_SHARDS', () => {
    assert.equal(planShards(100000), MAX_SHARDS)
})

test('planOutputs skips the jest job when no test is related', () => {
    const outputs = planOutputs({ changedFiles: ['src/types-only.ts'], changedFileCount: 1, testCount: 0 })

    assert.equal(outputs.should_run, 'false')
    assert.equal(outputs.shard_count, '0')
    assert.deepEqual(JSON.parse(outputs.matrix), { include: [] })
})

test('planOutputs emits one matrix cell per shard with the shared shard_count', () => {
    const outputs = planOutputs({ changedFiles: ['src/a.ts', 'src/b.ts'], changedFileCount: 7, testCount: 1200 })
    const matrix = JSON.parse(outputs.matrix)

    assert.equal(outputs.should_run, 'true')
    assert.equal(outputs.selected_file_count, '2')
    assert.equal(outputs.changed_file_count, '7')
    assert.equal(outputs.related_test_count, '1200')
    assert.equal(String(matrix.include.length), outputs.shard_count)
    assert.deepEqual(matrix.include[0], { segment: 'app', chunk: 1, shard_count: matrix.include.length })
    assert.deepEqual(
        matrix.include.map((cell) => cell.chunk),
        matrix.include.map((_, i) => i + 1)
    )
})
