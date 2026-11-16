import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const verifier = fileURLToPath(new URL('./verify-storybook-new-stories.sh', import.meta.url))

for (const { changedStory, failureBrowser, expectedStatus, changedRuns } of [
    { changedStory: true, failureBrowser: '', expectedStatus: 0, changedRuns: 4 },
    { changedStory: true, failureBrowser: 'chromium', expectedStatus: 1, changedRuns: 4 },
    { changedStory: true, failureBrowser: 'webkit', expectedStatus: 1, changedRuns: 4 },
    { changedStory: false, failureBrowser: '', expectedStatus: 0, changedRuns: 0 },
]) {
    test(`changed story=${changedStory}, failing browser=${failureBrowser}`, () => {
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
            if (changedStory) {
                writeFileSync(path.join(cwd, changed), 'after')
            }
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
                'change',
                '--allow-empty'
            )
            writeFileSync(
                path.join(bin, 'pnpm'),
                '#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALLS"\ncase "$*" in *"--browsers $FAILURE_BROWSER "*) [ -z "$FAILURE_BROWSER" ] || exit 1 ;; esac\nexit 0\n',
                {
                    mode: 0o755,
                }
            )
            const callsPath = path.join(cwd, 'calls')
            const result = spawnSync('bash', [verifier, base, '3'], {
                cwd,
                encoding: 'utf8',
                env: {
                    ...process.env,
                    PATH: `${bin}:${process.env.PATH}`,
                    CALLS: callsPath,
                    FAILURE_BROWSER: failureBrowser,
                    AFFECTED_FILES_JSON: JSON.stringify([changed, unchanged]),
                },
            })
            assert.equal(result.status, expectedStatus, result.stdout + result.stderr)
            const calls = existsSync(callsPath) ? readFileSync(callsPath, 'utf8').trim().split('\n') : []
            assert.equal(calls.filter((call) => call.includes('Changed\\.stories')).length, changedRuns)
            assert.equal(calls.filter((call) => call.includes('Unchanged\\.stories')).length, 0)
            if (changedRuns) {
                assert.equal(calls.filter((call) => call.includes('--browsers webkit')).length, 1)
            }
        } finally {
            rmSync(cwd, { recursive: true, force: true })
        }
    })
}
