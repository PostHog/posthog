import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const verifier = fileURLToPath(new URL('./verify-storybook-new-stories.sh', import.meta.url))

for (const { phase, affected, fail, expectedStatus, changedRuns, affectedRuns } of [
    { phase: '', affected: false, fail: true, expectedStatus: 1, changedRuns: 4, affectedRuns: 0 },
    { phase: 'all', affected: true, fail: false, expectedStatus: 0, changedRuns: 4, affectedRuns: 2 },
    { phase: 'affected', affected: true, fail: false, expectedStatus: 0, changedRuns: 0, affectedRuns: 2 },
    { phase: 'affected', affected: true, fail: true, expectedStatus: 0, changedRuns: 0, affectedRuns: 1 },
]) {
    test(`${phase} phase, affected=${affected}, runner fails=${fail}`, () => {
        const cwd = mkdtempSync(path.join(os.tmpdir(), 'storybook-verifier-'))
        try {
            const bin = path.join(cwd, 'bin')
            const changed = 'frontend/src/Changed.stories.tsx'
            const unchanged = 'frontend/src/Unchanged.stories.tsx'
            mkdirSync(bin)
            mkdirSync(path.dirname(path.join(cwd, changed)), { recursive: true })
            writeFileSync(path.join(cwd, changed), 'before')
            writeFileSync(path.join(cwd, unchanged), 'unchanged')
            const git = (...args) => {
                const result = spawnSync('git', args, { cwd, encoding: 'utf8' })
                assert.equal(result.status, 0, result.stderr)
                return result.stdout.trim()
            }
            git('init', '-q')
            git('add', '.')
            git(
                '-c',
                'commit.gpgsign=false',
                '-c',
                'user.name=Test',
                '-c',
                'user.email=test@example.com',
                'commit',
                '-qm',
                'initial'
            )
            const base = git('rev-parse', 'HEAD')
            writeFileSync(path.join(cwd, changed), 'after')
            git('add', '.')
            git(
                '-c',
                'commit.gpgsign=false',
                '-c',
                'user.name=Test',
                '-c',
                'user.email=test@example.com',
                'commit',
                '-qm',
                'change'
            )
            writeFileSync(path.join(bin, 'pnpm'), '#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALLS"\nexit "$RUNNER_EXIT"\n', {
                mode: 0o755,
            })
            writeFileSync(path.join(bin, 'timeout'), '#!/bin/sh\nshift 2\nexec "$@"\n', { mode: 0o755 })
            const callsPath = path.join(cwd, 'calls')
            const summaryPath = path.join(cwd, 'summary')
            const result = spawnSync('bash', [verifier, base, '3'], {
                cwd,
                encoding: 'utf8',
                env: {
                    ...process.env,
                    PATH: `${bin}:${process.env.PATH}`,
                    CALLS: callsPath,
                    RUNNER_EXIT: fail ? '1' : '0',
                    STORYBOOK_VERIFY_PHASE: phase,
                    AFFECTED_FILES_JSON: JSON.stringify(affected ? [changed, unchanged] : []),
                    GITHUB_STEP_SUMMARY: summaryPath,
                },
            })
            assert.equal(result.status, expectedStatus, result.stdout + result.stderr)
            const calls = readFileSync(callsPath, 'utf8').trim().split('\n')
            assert.equal(calls.filter((call) => call.includes('Changed\\.stories')).length, changedRuns)
            assert.equal(calls.filter((call) => call.includes('Unchanged\\.stories')).length, affectedRuns)
            if (changedRuns) {
                assert.equal(calls.filter((call) => call.includes('--browsers webkit')).length, 1)
            }
            if (affected) {
                assert.match(
                    readFileSync(summaryPath, 'utf8'),
                    fail ? /did not complete cleanly/ : /passed for 1 files/
                )
            }
        } finally {
            rmSync(cwd, { recursive: true, force: true })
        }
    })
}
