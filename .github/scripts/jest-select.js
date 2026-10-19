#!/usr/bin/env node
const { execFileSync } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')

const FRONTEND_DIR = path.resolve(__dirname, '../../frontend')

// File counts approximate runtime; tune this from observed shard durations.
const TEST_FILES_PER_SHARD = 342
const MAX_SHARDS = 8
const MAX_CHANGED_FILES = 200

/** @typedef {{ mode: 'selective', changedFiles: string[], changedFileCount: number }} Candidate */
/** @typedef {{ mode: 'full' | 'skip', changedFileCount: number | null, reason: { category: string, detail: string } }} Fallback */
/** @typedef {(Candidate & { testCount: number }) | Fallback} Selection */

/** @returns {Fallback} */
function fallback(isDraft, changedFileCount, category, detail) {
    // Drafts defer uncertain selection to their ready run; ready PRs need coverage now.
    return { mode: isDraft ? 'skip' : 'full', changedFileCount, reason: { category, detail } }
}

/** @returns {Candidate | Fallback} */
function classifyChanges({ files, diffOutcome, isDraft }) {
    if (diffOutcome !== 'success' || files.length === 0) {
        return fallback(isDraft, null, 'diff_unavailable', diffOutcome)
    }
    const changedFileCount = files.length
    if (changedFileCount > MAX_CHANGED_FILES) {
        return fallback(isDraft, changedFileCount, 'over_ceiling', `${changedFileCount} files`)
    }
    for (const file of files) {
        if (
            /^frontend\/jest\./.test(file) ||
            /^tsconfig\..*\.json$/.test(file) ||
            [
                'babel.config.js',
                'tsconfig.json',
                'package.json',
                'pnpm-lock.yaml',
                'webpack.config.js',
                '.github/workflows/ci-frontend.yml',
                '.github/scripts/jest-retries.cjs',
                '.github/scripts/jest-select.js',
                'patches/jest-junit@16.0.0.patch',
                '.nvmrc',
            ].includes(file)
        ) {
            return fallback(isDraft, changedFileCount, 'config_change', file)
        }
        // These dependencies are loaded outside Jest's runtime import graph.
        if (
            file.startsWith('common/replay-shared/src/') ||
            file.startsWith('frontend/src/mocks/') ||
            file === 'frontend/src/lib/api.mock.ts'
        ) {
            return fallback(isDraft, changedFileCount, 'unindexed_dependency', file)
        }
    }
    const changedFiles = files
        .filter((file) => /\.(ts|tsx|js|jsx|mjs|cjs|json)$/.test(file))
        .filter((file) => /^(frontend|products|common|ee\/frontend)\//.test(file))
        .map((file) => (file.startsWith('frontend/') ? file.slice('frontend/'.length) : `../${file}`))
    return { mode: 'selective', changedFiles, changedFileCount }
}

function listRelatedTests(changedFiles) {
    // The package's jest command runs build:products, as the test job does.
    const output = execFileSync('pnpm', ['jest', '--listTests', '--findRelatedTests', ...changedFiles], {
        cwd: FRONTEND_DIR,
        encoding: 'utf8',
        timeout: 2 * 60 * 1000,
        maxBuffer: 256 * 1024 * 1024,
        stdio: ['ignore', 'pipe', 'inherit'],
    })
    return output.split('\n').filter((line) => line.startsWith('/'))
}

/** @returns {Selection} */
function selectTests(input, findRelatedTests) {
    const candidate = classifyChanges(input)
    if (candidate.mode !== 'selective') {
        return candidate
    }
    if (candidate.changedFiles.length === 0) {
        return { ...candidate, testCount: 0 }
    }
    if (input.installOutcome === 'success') {
        try {
            return { ...candidate, testCount: findRelatedTests(candidate.changedFiles).length }
        } catch (error) {
            console.error(`Test selection failed: ${error.message}`)
        }
    }
    return fallback(input.isDraft, candidate.changedFileCount, 'selector_crash', 'Jest selection unavailable')
}

/** @param {Selection} selection */
function workflowOutputs(selection) {
    const selective = selection.mode === 'selective'
    const shardCount = selective
        ? Math.min(MAX_SHARDS, Math.ceil(selection.testCount / TEST_FILES_PER_SHARD))
        : selection.mode === 'full'
          ? 4
          : 0
    return {
        mode: selection.mode,
        // The test job supplies its full matrix when this output is empty.
        matrix:
            selection.mode === 'full'
                ? ''
                : JSON.stringify({
                      include: Array.from({ length: shardCount }, (_, i) => ({
                          segment: 'app',
                          chunk: i + 1,
                          shard_count: shardCount,
                      })),
                  }),
        should_run: shardCount > 0,
        changed_files: selective ? selection.changedFiles.join(' ') : '',
        changed_file_count: selection.changedFileCount ?? '',
        selected_file_count: selective ? selection.changedFiles.length : 0,
        related_test_count: selective ? selection.testCount : '',
        shard_count: shardCount,
        full_run_reason_category: selective ? '' : selection.reason.category,
        full_run_reason_detail: selective ? '' : selection.reason.detail,
    }
}

function main() {
    const filesPath = process.env.CHANGED_FILES_PATH ?? '/tmp/changed.txt'
    const input = {
        files: fs.existsSync(filesPath) ? fs.readFileSync(filesPath, 'utf8').split('\n').filter(Boolean) : [],
        diffOutcome: process.env.DIFF_OUTCOME ?? '',
        isDraft: process.env.PR_DRAFT === 'true',
        installOutcome: process.env.INSTALL_OUTCOME ?? '',
    }
    let outputs
    if (process.argv[2] === 'prepare') {
        const candidate = classifyChanges(input)
        outputs = { needs_dependencies: candidate.mode === 'selective' && candidate.changedFiles.length > 0 }
    } else {
        const selection = selectTests(input, listRelatedTests)
        if (selection.mode !== 'selective') {
            console.log(`Selection ${selection.mode}: ${selection.reason.category} (${selection.reason.detail})`)
        }
        outputs = workflowOutputs(selection)
    }
    fs.appendFileSync(
        process.env.GITHUB_OUTPUT ?? '/dev/stdout',
        Object.entries(outputs)
            .map(([key, value]) => `${key}=${value}\n`)
            .join('')
    )
}

if (require.main === module) {
    main()
}

module.exports = { classifyChanges, selectTests, workflowOutputs }
