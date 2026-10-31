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
    const sources = files
        .filter((file) => /\.(ts|tsx|js|jsx|mjs|cjs|json)$/.test(file))
        .filter((file) => /^(frontend|products|common|ee\/frontend)\//.test(file))
        .map((file) => (file.startsWith('frontend/') ? file.slice('frontend/'.length) : `../${file}`))
    // Listing must use the same space-separated arguments as the test job.
    const changedFiles = sources.join(' ').split(' ').filter(Boolean)
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
            console.log('::notice::Test selection failed; using the prepared fallback')
        }
    }
    return fallback(input.isDraft, candidate.changedFileCount, 'selector_crash', 'Jest selection unavailable')
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
                segment: 'app',
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

/** @param {Selection} selection */
function workflowOutputs(selection) {
    if (selection.mode === 'selective') {
        return planOutputs(selection)
    }
    return {
        mode: selection.mode,
        // The test job supplies its full matrix when this output is empty.
        matrix: selection.mode === 'full' ? '' : '{"include":[]}',
        should_run: String(selection.mode === 'full'),
        changed_files: '',
        changed_file_count: String(selection.changedFileCount ?? ''),
        selected_file_count: '0',
        shard_count: selection.mode === 'full' ? '4' : '0',
        full_run_reason_category: selection.reason.category,
        full_run_reason_detail: selection.reason.detail,
    }
}

function main() {
    let outputs
    if (process.argv[2] === undefined) {
        const changedFiles = (process.env.CHANGED_FILES ?? '').split(' ').filter(Boolean)
        const testCount = changedFiles.length === 0 ? 0 : listRelatedTests(changedFiles).length
        outputs = planOutputs({ changedFiles, changedFileCount: process.env.CHANGED_FILE_COUNT ?? '', testCount })
    } else {
        const filesPath = process.env.CHANGED_FILES_PATH ?? '/tmp/changed.txt'
        const input = {
            files: fs.existsSync(filesPath) ? fs.readFileSync(filesPath, 'utf8').split('\n').filter(Boolean) : [],
            diffOutcome: process.env.DIFF_OUTCOME ?? '',
            isDraft: process.env.PR_DRAFT === 'true',
            installOutcome: process.env.INSTALL_OUTCOME ?? '',
        }
        if (process.argv[2] === 'prepare') {
            const candidate = classifyChanges(input)
            outputs = { needs_dependencies: candidate.mode === 'selective' && candidate.changedFiles.length > 0 }
        } else if (process.argv[2] === 'select') {
            const selection = selectTests(input, listRelatedTests)
            if (selection.mode !== 'selective' && selection.reason.category !== 'selector_crash') {
                const behavior =
                    selection.mode === 'skip'
                        ? 'draft skips jest (its ready run selects again)'
                        : 'running the full jest matrix'
                console.log(`::notice::${selection.reason.category} (${selection.reason.detail}); ${behavior}`)
            }
            outputs = workflowOutputs(selection)
        } else {
            throw new Error('Expected prepare or select, or no command for CHANGED_FILES input')
        }
    }
    fs.appendFileSync(
        process.env.GITHUB_OUTPUT ?? '/dev/stdout',
        Object.entries(outputs)
            .map(([key, value]) => `${key}=${value}\n`)
            .join('')
    )
    if (outputs.mode === 'selective') {
        console.log(
            `Selective mode: ${outputs.selected_file_count} changed files, ${outputs.related_test_count} related tests, ${outputs.shard_count} shards`
        )
    }
}

if (require.main === module) {
    main()
}

module.exports = {
    classifyChanges,
    selectTests,
    workflowOutputs,
    planShards,
    planOutputs,
    TEST_FILES_PER_SHARD,
    MAX_SHARDS,
}
