#!/usr/bin/env node
// Sizes the PR jest matrix from the count of tests related to the changed files: lists them the
// way the jest job will, then writes the matrix and the counts to GITHUB_OUTPUT.
//
// Run with: CHANGED_FILES="src/a.ts ../products/b.ts" node .github/scripts/jest-select.js

const { execFileSync } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')

const FRONTEND_DIR = path.resolve(__dirname, '../../frontend')

// Initial limit from the probes documented in docs/internal/ci-things-already-tried.md.
// File counts approximate runtime; tune this from observed shard durations.
const TEST_FILES_PER_SHARD = 342
const MAX_SHARDS = 8
const SEGMENT = 'app'

function listRelatedTests(changedFiles) {
    if (changedFiles.length === 0) {
        return []
    }
    // The package's `jest` script runs build:products first, like the jest job does.
    const args = ['jest', '--listTests', '--findRelatedTests', ...changedFiles]
    const output = execFileSync('pnpm', args, {
        cwd: FRONTEND_DIR,
        encoding: 'utf8',
        timeout: 2 * 60 * 1000,
        maxBuffer: 256 * 1024 * 1024,
        stdio: ['ignore', 'pipe', 'inherit'],
    })
    return output.split('\n').filter((line) => line.startsWith('/'))
}

function planShards(testCount) {
    return Math.min(MAX_SHARDS, Math.ceil(testCount / TEST_FILES_PER_SHARD))
}

function planOutputs({ changedFiles, changedFileCount, testCount }) {
    const shardCount = planShards(testCount)
    return {
        mode: 'selective',
        matrix: JSON.stringify({
            include: Array.from({ length: shardCount }, (_, i) => ({
                segment: SEGMENT,
                chunk: i + 1,
                shard_count: shardCount,
            })),
        }),
        should_run: String(shardCount > 0),
        changed_files: changedFiles.join(' '),
        changed_file_count: String(changedFileCount),
        selected_file_count: String(changedFiles.length),
        related_test_count: String(testCount),
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
        `Selective mode: ${changedFiles.length} changed files, ${testCount} related tests, ${outputs.shard_count} shards`
    )
}

if (require.main === module) {
    main()
}

module.exports = { planShards, planOutputs, TEST_FILES_PER_SHARD, MAX_SHARDS }
