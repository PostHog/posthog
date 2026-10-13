// Run with: node --test .github/scripts/jest-select.test.js

const test = require('node:test')
const assert = require('node:assert/strict')
const crypto = require('node:crypto')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const {
    parseJunitDurations,
    shardTests,
    estimateWallSeconds,
    planShards,
    planOutputs,
    TARGET_WALL_SECONDS,
    JOB_OVERHEAD_SECONDS,
    UNKNOWN_FILE_SECONDS,
    MAX_SHARDS,
} = require('./jest-select.js')

const sha1 = (text) => crypto.createHash('sha1').update(text).digest('hex')

test('parseJunitDurations keys each suite by its file path and keeps the slowest record', () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'jest-select-'))
    fs.mkdirSync(path.join(dir, 'app-1'))
    fs.writeFileSync(
        path.join(dir, 'app-1', 'junit-app-1.xml'),
        `<?xml version="1.0" encoding="UTF-8"?>
<testsuites name="jest tests" tests="2" failures="0" errors="0" time="20.5">
  <testsuite name="src/a.test.ts" errors="0" failures="0" skipped="0" timestamp="2026-10-13T14:30:47" time="17.811" tests="1">
    <testcase classname="a" name="a" time="0.082" file="src/a.test.ts"></testcase>
  </testsuite>
  <testsuite name="../products/x/frontend/b.test.tsx" errors="0" failures="0" skipped="0" timestamp="2026-10-13T14:30:47" time="2.5" tests="1">
  </testsuite>
</testsuites>`
    )
    fs.writeFileSync(
        path.join(dir, 'junit-app-2.xml'),
        `<testsuites><testsuite name="src/a.test.ts" time="3.0" tests="1"></testsuite></testsuites>`
    )

    assert.deepEqual(parseJunitDurations(dir), { 'src/a.test.ts': 17.811, '../products/x/frontend/b.test.tsx': 2.5 })
})

test('shardTests splits the sha1-ordered list the way jest --shard does', () => {
    const tests = ['src/a.test.ts', 'src/b.test.ts', 'src/c.test.ts', 'src/d.test.ts', 'src/e.test.ts']
    const shards = shardTests(tests, 3)

    assert.deepEqual(
        shards.map((shard) => shard.length),
        [2, 2, 1]
    )
    assert.deepEqual(
        shards.flat(),
        [...tests].sort((a, b) => (sha1(a) < sha1(b) ? -1 : 1))
    )
})

test('estimateWallSeconds prices an unknown file at the fallback', () => {
    const known = estimateWallSeconds(['src/a.test.ts'], { 'src/a.test.ts': 30 })
    const unknown = estimateWallSeconds(['src/new.test.ts'], { 'src/a.test.ts': 30 })

    assert.equal(known, JOB_OVERHEAD_SECONDS + Math.round((30 * 1.4) / 3))
    assert.equal(unknown, JOB_OVERHEAD_SECONDS + Math.round((UNKNOWN_FILE_SECONDS * 1.4) / 3))
})

test('planShards gives a small selection one shard and a large one enough to meet the target', () => {
    const small = Array.from({ length: 150 }, (_, i) => `src/small-${i}.test.ts`)
    const durations = Object.fromEntries(small.map((file) => [file, 3]))
    assert.deepEqual(planShards(small, durations), { shardCount: 1, estimatedSeconds: 330 })

    const large = Array.from({ length: 2000 }, (_, i) => `src/large-${i}.test.ts`)
    Object.assign(durations, Object.fromEntries(large.map((file) => [file, 2.3])))
    const plan = planShards(large, durations)
    assert.ok(plan.estimatedSeconds <= TARGET_WALL_SECONDS, `slowest shard ${plan.estimatedSeconds}s`)
    assert.ok(plan.shardCount > 1 && plan.shardCount < MAX_SHARDS, `${plan.shardCount} shards`)
    assert.ok(
        Math.max(...shardTests(large, plan.shardCount - 1).map((s) => estimateWallSeconds(s, durations))) >
            TARGET_WALL_SECONDS,
        'one shard fewer would miss the target'
    )
})

test('planShards caps the count at MAX_SHARDS when no count meets the target', () => {
    const tests = Array.from({ length: 50 }, (_, i) => `src/slow-${i}.test.ts`)
    const durations = Object.fromEntries(tests.map((file) => [file, 2000]))

    assert.equal(planShards(tests, durations).shardCount, MAX_SHARDS)
})

test('planOutputs skips the jest job when no test is related', () => {
    const outputs = planOutputs({ changedFiles: ['src/types-only.ts'], changedFileCount: 1, tests: [], durations: {} })

    assert.equal(outputs.should_run, 'false')
    assert.equal(outputs.shard_count, '0')
    assert.equal(outputs.related_test_count, '0')
    assert.deepEqual(JSON.parse(outputs.matrix), { include: [] })
})

test('planOutputs emits one matrix cell per shard with the shared shard_count', () => {
    const tests = Array.from({ length: 1200 }, (_, i) => `src/t-${i}.test.ts`)
    const outputs = planOutputs({ changedFiles: ['src/a.ts', 'src/b.ts'], changedFileCount: 7, tests, durations: {} })
    const matrix = JSON.parse(outputs.matrix)

    assert.equal(outputs.should_run, 'true')
    assert.equal(outputs.selected_file_count, '2')
    assert.equal(outputs.changed_file_count, '7')
    assert.equal(String(matrix.include.length), outputs.shard_count)
    assert.deepEqual(matrix.include[0], { segment: 'app', chunk: 1, shard_count: matrix.include.length })
    assert.deepEqual(
        matrix.include.map((cell) => cell.chunk),
        matrix.include.map((_, i) => i + 1)
    )
})
