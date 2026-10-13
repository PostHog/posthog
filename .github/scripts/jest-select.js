#!/usr/bin/env node
// Sizes the PR jest matrix from the count of tests related to the changed files: lists them the
// way the jest job will, then writes the matrix and the counts to GITHUB_OUTPUT.
//
// Run with: CHANGED_FILES="src/a.ts ../products/b.ts" node .github/scripts/jest-select.js

const { execFileSync } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')

const FRONTEND_DIR = path.resolve(__dirname, '../../frontend')

// The slowest shard job of a PR run should finish within this wall on the slowest
// ubuntu-24.04 CPU (EPYC 7763). The jest job times out at twice this.
const TARGET_WALL_SECONDS = 10 * 60
// Checkout, pnpm install, build:products and jest startup, before the first test runs.
const JOB_OVERHEAD_SECONDS = 120
// Mean worker seconds per test file on the fastest ubuntu-24.04 CPU (EPYC 9V45), from the
// hourly run's JUnit. Tests that load the dashboard import cycle cost about 3.7, the rest 1.1.
const SECONDS_PER_TEST_FILE = 3
// The slowest ubuntu-24.04 CPU runs the same shard 1.4x slower than the fastest one.
const SLOW_CPU_FACTOR = 1.4
// Jest's default worker count on a 4 vCPU runner is cores minus one.
const WORKERS = 3
const MAX_SHARDS = 8
const SEGMENT = 'app'

const TEST_FILES_PER_SHARD = Math.floor(
    ((TARGET_WALL_SECONDS - JOB_OVERHEAD_SECONDS) * WORKERS) / (SECONDS_PER_TEST_FILE * SLOW_CPU_FACTOR)
)

function listRelatedTests(changedFiles) {
    execFileSync('pnpm', ['build:products'], { cwd: FRONTEND_DIR, stdio: ['ignore', 'ignore', 'inherit'] })
    // watchman hangs jest in a fresh checkout, and the crawler does not change the list.
    const args = ['exec', 'jest', '--listTests', '--watchman=false', '--findRelatedTests', ...changedFiles]
    const output = execFileSync('pnpm', args, {
        cwd: FRONTEND_DIR,
        encoding: 'utf8',
        maxBuffer: 256 * 1024 * 1024,
        stdio: ['ignore', 'pipe', 'inherit'],
    })
    return output.split('\n').filter((line) => line.startsWith('/'))
}

function planShards(testCount) {
    const shardCount = Math.min(MAX_SHARDS, Math.ceil(testCount / TEST_FILES_PER_SHARD))
    const filesOnSlowestShard = Math.ceil(testCount / Math.max(shardCount, 1))
    const estimatedSeconds =
        shardCount === 0
            ? 0
            : Math.round(
                  JOB_OVERHEAD_SECONDS + (filesOnSlowestShard * SECONDS_PER_TEST_FILE * SLOW_CPU_FACTOR) / WORKERS
              )
    return { shardCount, estimatedSeconds }
}

function buildMatrix(shardCount) {
    const include = []
    for (let chunk = 1; chunk <= shardCount; chunk++) {
        include.push({ segment: SEGMENT, chunk, shard_count: shardCount })
    }
    return { include }
}

function planOutputs({ changedFiles, changedFileCount, testCount }) {
    const { shardCount, estimatedSeconds } = planShards(testCount)
    return {
        mode: 'selective',
        matrix: JSON.stringify(buildMatrix(shardCount)),
        should_run: String(shardCount > 0),
        changed_files: changedFiles.join(' '),
        changed_file_count: String(changedFileCount),
        selected_file_count: String(changedFiles.length),
        related_test_count: String(testCount),
        estimated_seconds: String(estimatedSeconds),
        shard_count: String(shardCount),
        full_run_reason_category: '',
        full_run_reason_detail: '',
    }
}

function main() {
    const changedFiles = (process.env.CHANGED_FILES ?? '').split(' ').filter(Boolean)
    const testCount = listRelatedTests(changedFiles).length
    const outputs = planOutputs({ changedFiles, changedFileCount: process.env.CHANGED_FILE_COUNT ?? '', testCount })
    const lines = Object.entries(outputs).map(([key, value]) => `${key}=${value}\n`)
    fs.appendFileSync(process.env.GITHUB_OUTPUT ?? '/dev/stdout', lines.join(''))
    console.log(
        `Selective mode: ${changedFiles.length} changed files, ${testCount} related tests, ` +
            `${outputs.shard_count} shards, slowest estimated at ${outputs.estimated_seconds}s`
    )
}

if (require.main === module) {
    main()
}

module.exports = { planShards, planOutputs, TARGET_WALL_SECONDS, TEST_FILES_PER_SHARD, MAX_SHARDS }
