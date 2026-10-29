const test = require('node:test')
const assert = require('node:assert/strict')
const { spawnSync } = require('node:child_process')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const { classifyChanges, selectTests, workflowOutputs } = require('./jest-select.js')

const ready = { diffOutcome: 'success', isDraft: false }

for (const [name, input, category] of [
    ['failed diff', { files: ['frontend/src/a.ts'], diffOutcome: 'failure' }, 'diff_unavailable'],
    ['empty diff', { files: [] }, 'diff_unavailable'],
    ['oversized diff', { files: Array.from({ length: 201 }, (_, i) => `frontend/src/${i}.ts`) }, 'over_ceiling'],
    ['Jest config', { files: ['frontend/jest.config.js'] }, 'config_change'],
    ['TypeScript config', { files: ['tsconfig.paths.json'] }, 'config_change'],
    ['lockfile', { files: ['pnpm-lock.yaml'] }, 'config_change'],
    ['selector itself', { files: ['.github/scripts/jest-select.js'] }, 'config_change'],
    ['Jest setup dependency', { files: ['frontend/src/mocks/handlers.ts'] }, 'unindexed_dependency'],
    ['API mock', { files: ['frontend/src/lib/api.mock.ts'] }, 'unindexed_dependency'],
    ['replay shared', { files: ['common/replay-shared/src/index.ts'] }, 'unindexed_dependency'],
]) {
    for (const isDraft of [false, true]) {
        test(`${name} ${isDraft ? 'defers a draft' : 'runs the full ready PR matrix'}`, () => {
            const selection = classifyChanges({ ...ready, ...input, isDraft })
            assert.equal(selection.mode, isDraft ? 'skip' : 'full')
            assert.equal(selection.reason.category, category)
            const outputs = workflowOutputs(selection)
            assert.equal(outputs.should_run, String(!isDraft))
            assert.equal(outputs.matrix, isDraft ? '{"include":[]}' : '')
        })
    }
}

test('selection resolves source paths from the frontend package and retains the total diff count', () => {
    assert.deepEqual(
        classifyChanges({
            ...ready,
            files: [
                'frontend/src/a.ts',
                'products/example/frontend/a.tsx',
                'common/example/data.json',
                'ee/frontend/a.js',
                'frontend/src/a.scss',
                'posthog/example.py',
                'docs/example.md',
            ],
        }),
        {
            mode: 'selective',
            changedFiles: [
                'src/a.ts',
                '../products/example/frontend/a.tsx',
                '../common/example/data.json',
                '../ee/frontend/a.js',
            ],
            changedFileCount: 7,
        }
    )
})

test('the changed-file ceiling includes its boundary', () => {
    const files = Array.from({ length: 200 }, (_, i) => `frontend/src/${i}.ts`)
    assert.equal(classifyChanges({ ...ready, files }).mode, 'selective')
})

for (const [testCount, shardCount] of [
    [0, 0],
    [342, 1],
    [343, 2],
    [1200, 4],
    [2000, 6],
    [100000, 8],
]) {
    test(`${testCount} related tests use ${shardCount} shards`, () => {
        const selection = selectTests({ ...ready, files: ['frontend/src/a.ts'], installOutcome: 'success' }, () =>
            Array(testCount)
        )
        const outputs = workflowOutputs(selection)
        assert.equal(outputs.shard_count, String(shardCount))
        assert.equal(outputs.should_run, String(shardCount > 0))
        assert.equal(outputs.changed_file_count, '1')
        assert.equal(outputs.related_test_count, String(testCount))
        assert.deepEqual(JSON.parse(outputs.matrix), {
            include: Array.from({ length: shardCount }, (_, i) => ({
                segment: 'app',
                chunk: i + 1,
                shard_count: shardCount,
            })),
        })
    })
}

for (const isDraft of [false, true]) {
    for (const failure of ['install', 'listing']) {
        test(`${failure} failure ${isDraft ? 'defers a draft' : 'runs all tests on a ready PR'}`, () => {
            const selection = selectTests(
                {
                    ...ready,
                    isDraft,
                    files: ['frontend/src/a.ts'],
                    installOutcome: failure === 'install' ? 'failure' : 'success',
                },
                () => {
                    throw new Error('test listing unavailable')
                }
            )
            assert.deepEqual(selection, {
                mode: isDraft ? 'skip' : 'full',
                changedFileCount: 1,
                reason: { category: 'selector_crash', detail: 'Jest selection unavailable' },
            })
        })
    }
}

test('a diff without Jest sources needs neither dependencies nor test listing', () => {
    const selection = selectTests({ ...ready, files: ['frontend/src/a.scss'], installOutcome: 'skipped' }, () => {
        assert.fail('must not invoke Jest for an empty source selection')
    })
    assert.equal(selection.mode, 'selective')
    assert.equal(workflowOutputs(selection).should_run, 'false')
})

test('the CLI prepares dependency installation and writes the final fallback without temporary state', () => {
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'jest-selection-'))
    try {
        const changedFiles = path.join(directory, 'changed.txt')
        fs.writeFileSync(changedFiles, 'frontend/src/a.ts\n')
        for (const [args, expected] of [
            [['prepare'], { needs_dependencies: 'true' }],
            [
                ['select'],
                {
                    mode: 'full',
                    should_run: 'true',
                    changed_file_count: '1',
                    full_run_reason_category: 'selector_crash',
                },
            ],
        ]) {
            const output = path.join(directory, args[0])
            const result = spawnSync(process.execPath, [path.join(__dirname, 'jest-select.js'), ...args], {
                encoding: 'utf8',
                env: {
                    CHANGED_FILES_PATH: changedFiles,
                    DIFF_OUTCOME: 'success',
                    PR_DRAFT: 'false',
                    INSTALL_OUTCOME: 'failure',
                    GITHUB_OUTPUT: output,
                },
            })
            assert.deepEqual({ status: result.status, stderr: result.stderr }, { status: 0, stderr: '' })
            const outputs = Object.fromEntries(
                fs
                    .readFileSync(output, 'utf8')
                    .trimEnd()
                    .split('\n')
                    .map((line) => {
                        const equals = line.indexOf('=')
                        return [line.slice(0, equals), line.slice(equals + 1)]
                    })
            )
            for (const [key, value] of Object.entries(expected)) {
                assert.equal(outputs[key], value)
            }
        }
    } finally {
        fs.rmSync(directory, { recursive: true, force: true })
    }
})

test("listing keeps the test job's existing space-separated argument contract", () => {
    const selection = selectTests({ ...ready, files: ['frontend/src/a b.ts'], installOutcome: 'success' }, (files) => {
        assert.deepEqual(files, ['src/a', 'b.ts'])
        return []
    })
    assert.equal(workflowOutputs(selection).selected_file_count, '2')
})

for (const [name, changedFiles, listingExit, expectedCount] of [
    ['success', 'src/a.ts ../products/example/a.tsx', 0, '2'],
    ['empty input', '', 1, '0'],
    ['listing failure', 'src/a.ts', 1, null],
]) {
    test(`the original CHANGED_FILES CLI retains its ${name} behavior`, () => {
        const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'jest-selection-cli-'))
        try {
            fs.writeFileSync(
                path.join(directory, 'pnpm'),
                '#!/bin/sh\nprintf "/test-a\\n/test-b\\n"\nexit "$LISTING_EXIT"\n',
                { mode: 0o755 }
            )
            const output = path.join(directory, 'output')
            const result = spawnSync(process.execPath, [path.join(__dirname, 'jest-select.js')], {
                encoding: 'utf8',
                env: {
                    PATH: directory,
                    CHANGED_FILES: changedFiles,
                    CHANGED_FILE_COUNT: '7',
                    LISTING_EXIT: String(listingExit),
                    GITHUB_OUTPUT: output,
                },
            })
            if (expectedCount === null) {
                assert.equal(result.status, 1)
                assert.equal(fs.existsSync(output), false)
            } else {
                assert.deepEqual({ status: result.status, stderr: result.stderr }, { status: 0, stderr: '' })
                assert.match(fs.readFileSync(output, 'utf8'), new RegExp(`related_test_count=${expectedCount}\\n`))
                assert.match(fs.readFileSync(output, 'utf8'), /changed_file_count=7\n/)
                assert.match(result.stdout, /Selective mode:/)
            }
        } finally {
            fs.rmSync(directory, { recursive: true, force: true })
        }
    })
}
