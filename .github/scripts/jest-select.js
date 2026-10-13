#!/usr/bin/env node
// Sizes the PR jest matrix from the tests that are related to the changed files.
//
//   plan       lists the related tests the way the jest job will, estimates the wall of
//              every shard from recorded durations, and writes the matrix to GITHUB_OUTPUT
//   durations  reads the JUnit files of a full run and prints a test path -> seconds map
//
// Run with: node .github/scripts/jest-select.js <plan|durations> [args]

const { execFileSync } = require('node:child_process')
const crypto = require('node:crypto')
const fs = require('node:fs')
const path = require('node:path')

const FRONTEND_DIR = path.resolve(__dirname, '../../frontend')

// The slowest shard job of a PR run should finish within this wall on the slowest
// ubuntu-24.04 CPU (EPYC 7763). The jest job times out at twice this.
const TARGET_WALL_SECONDS = 10 * 60
// Checkout, pnpm install, build:products and jest startup, before the first test runs.
const JOB_OVERHEAD_SECONDS = 120
// Jest's default worker count on a 4 vCPU runner is cores minus one.
const WORKERS = 3
// Durations are recorded on whichever CPU the hourly run landed on. The slowest
// ubuntu-24.04 CPU runs the same shard 1.4x slower than the fastest one.
const SLOW_CPU_FACTOR = 1.4
// Recorded seconds for a test file the durations map does not know: a new file, or a
// cold cache. Close to the suite mean, so a cold cache still sizes by count sensibly.
const UNKNOWN_FILE_SECONDS = 3
const MAX_SHARDS = 8
const SEGMENT = 'app'

function parseJunitDurations(junitDir) {
    const durations = {}
    for (const file of walk(junitDir)) {
        if (!file.endsWith('.xml')) {
            continue
        }
        const xml = fs.readFileSync(file, 'utf8')
        // jest-junit writes one <testsuite> per test file with JEST_JUNIT_SUITE_NAME='{filepath}'.
        for (const match of xml.matchAll(/<testsuite [^>]*?name="([^"]+)"[^>]*? time="([\d.]+)"/g)) {
            const seconds = Number(match[2])
            durations[match[1]] = Math.max(durations[match[1]] ?? 0, seconds)
        }
    }
    return durations
}

function* walk(dir) {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name)
        if (entry.isDirectory()) {
            yield* walk(full)
        } else {
            yield full
        }
    }
}

// Jest's default sequencer orders tests by the sha1 of their rootDir-relative path and
// gives the first (length % shardCount) shards one extra test. Reproducing it here lets
// the plan price the exact shards the jest job will run.
function shardTests(tests, shardCount) {
    const sorted = tests
        .map((test) => ({ hash: crypto.createHash('sha1').update(test).digest('hex'), test }))
        .sort((a, b) => (a.hash < b.hash ? -1 : a.hash > b.hash ? 1 : 0))
        .map((entry) => entry.test)
    const base = Math.floor(sorted.length / shardCount)
    const extra = sorted.length % shardCount
    const shards = []
    let start = 0
    for (let index = 0; index < shardCount; index++) {
        const size = base + (index < extra ? 1 : 0)
        shards.push(sorted.slice(start, start + size))
        start += size
    }
    return shards
}

function estimateWallSeconds(tests, durations) {
    const recorded = tests.reduce((sum, test) => sum + (durations[test] ?? UNKNOWN_FILE_SECONDS), 0)
    return Math.round(JOB_OVERHEAD_SECONDS + (recorded * SLOW_CPU_FACTOR) / WORKERS)
}

// The smallest shard count whose slowest shard fits the target, capped at MAX_SHARDS.
function planShards(tests, durations) {
    let plan = { shardCount: 0, estimatedSeconds: 0 }
    for (let shardCount = 1; shardCount <= MAX_SHARDS && tests.length > 0; shardCount++) {
        const estimatedSeconds = Math.max(
            ...shardTests(tests, shardCount).map((shard) => estimateWallSeconds(shard, durations))
        )
        plan = { shardCount, estimatedSeconds }
        if (estimatedSeconds <= TARGET_WALL_SECONDS) {
            break
        }
    }
    return plan
}

function buildMatrix(shardCount) {
    const include = []
    for (let chunk = 1; chunk <= shardCount; chunk++) {
        include.push({ segment: SEGMENT, chunk, shard_count: shardCount })
    }
    return { include }
}

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
    return output
        .split('\n')
        .filter((line) => line.startsWith('/'))
        .map((line) => path.posix.relative(FRONTEND_DIR, line))
}

function loadDurations(file) {
    if (!file || !fs.existsSync(file)) {
        return {}
    }
    return JSON.parse(fs.readFileSync(file, 'utf8'))
}

function planOutputs({ changedFiles, changedFileCount, tests, durations }) {
    const { shardCount, estimatedSeconds } = planShards(tests, durations)
    return {
        mode: 'selective',
        matrix: JSON.stringify(buildMatrix(shardCount)),
        should_run: String(shardCount > 0),
        changed_files: changedFiles.join(' '),
        changed_file_count: String(changedFileCount),
        selected_file_count: String(changedFiles.length),
        related_test_count: String(tests.length),
        estimated_seconds: String(estimatedSeconds),
        shard_count: String(shardCount),
        full_run_reason_category: '',
        full_run_reason_detail: '',
    }
}

function writeOutputs(outputs) {
    const lines = Object.entries(outputs).map(([key, value]) => `${key}=${value}\n`)
    fs.appendFileSync(process.env.GITHUB_OUTPUT, lines.join(''))
}

function main(argv) {
    const [command, ...args] = argv
    if (command === 'durations') {
        process.stdout.write(`${JSON.stringify(parseJunitDurations(args[0]), null, 0)}\n`)
        return
    }
    if (command === 'plan') {
        const changedFiles = (process.env.CHANGED_FILES ?? '').split(' ').filter(Boolean)
        const tests = listRelatedTests(changedFiles)
        const outputs = planOutputs({
            changedFiles,
            changedFileCount: process.env.CHANGED_FILE_COUNT ?? '',
            tests,
            durations: loadDurations(process.env.DURATIONS_FILE),
        })
        writeOutputs(outputs)
        console.log(
            `Selective mode: ${changedFiles.length} changed files, ${tests.length} related tests, ` +
                `${outputs.shard_count} shards, slowest estimated at ${outputs.estimated_seconds}s`
        )
        return
    }
    throw new Error(`usage: jest-select.js <plan|durations> [junit-dir]`)
}

if (require.main === module) {
    main(process.argv.slice(2))
}

module.exports = {
    parseJunitDurations,
    shardTests,
    estimateWallSeconds,
    planShards,
    planOutputs,
    TARGET_WALL_SECONDS,
    JOB_OVERHEAD_SECONDS,
    UNKNOWN_FILE_SECONDS,
    MAX_SHARDS,
}
