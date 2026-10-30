import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, it } from 'node:test'
import { fileURLToPath } from 'node:url'

import { EXEMPT_THROUGH_PR, checkStackDepth } from './check-stack-depth.mjs'

const layers = (...states) => states.map((state, i) => ({ number: EXEMPT_THROUGH_PR + 1 + i, state }))
const existingLayers = (count) =>
    Array.from({ length: count }, (_, i) => ({ number: EXEMPT_THROUGH_PR - count + 1 + i, state: 'open' }))

function runWithFakeGh(t, ghOutput, args = [], env = {}) {
    const directory = mkdtempSync(join(tmpdir(), 'stack-depth-'))
    t.after(() => rmSync(directory, { recursive: true, force: true }))
    const script = ghOutput === null ? 'exit 1' : `printf '%s' '${JSON.stringify(ghOutput)}'`
    writeFileSync(join(directory, 'gh'), `#!/bin/sh\n${script}\n`, { mode: 0o755 })
    return spawnSync(process.execPath, [fileURLToPath(new URL('./check-stack-depth.mjs', import.meta.url)), ...args], {
        env: { PATH: directory, ...env },
        encoding: 'utf-8',
        timeout: 5000,
    })
}

describe('checkStackDepth', () => {
    for (const { name, stack, expectedStatus } of [
        {
            name: 'rejects the sixth open layer',
            stack: layers('open', 'open', 'open', 'open', 'open', 'open'),
            expectedStatus: 'fail',
        },
        {
            name: 'skips merged layers below',
            stack: layers('closed', 'closed', 'closed', 'closed', 'open', 'open', 'open'),
            expectedStatus: 'pass',
        },
        {
            name: 'accepts five open layers',
            stack: layers('open', 'open', 'open', 'open', 'open'),
            expectedStatus: 'pass',
        },
        {
            name: 'keeps existing pull requests exempt',
            stack: existingLayers(6),
            expectedStatus: 'pass',
        },
        {
            name: 'rejects adding an unpublished layer to an exempt stack',
            stack: [...existingLayers(6), { state: 'open' }],
            expectedStatus: 'fail',
        },
    ]) {
        it(name, () => {
            assert.equal(checkStackDepth(stack).status, expectedStatus)
        })
    }
})

describe('local stack adapter', () => {
    for (const { name, current, closedBottom = false, expectedStatus } of [
        { name: 'fails pushing the sixth unpublished layer', current: 5, expectedStatus: 'fail' },
        { name: 'fails publishing from a lower layer of a deep stack', current: 1, expectedStatus: 'fail' },
        { name: 'skips a closed pull request below', current: 5, closedBottom: true, expectedStatus: 'pass' },
        {
            name: 'skips the trunk, which gh stack reports with no current branch',
            current: -1,
            expectedStatus: 'skipped',
        },
    ]) {
        it(name, (t) => {
            const branches = Array.from({ length: 6 }, (_, i) => ({ isMerged: false, isCurrent: i === current }))
            if (closedBottom) {
                branches[0].pr = { number: EXEMPT_THROUGH_PR + 1, state: 'CLOSED' }
            }
            const result = runWithFakeGh(t, { branches }, ['--local'])
            assert.equal(JSON.parse(result.stdout).status, expectedStatus, result.stderr)
            assert.equal(result.status, expectedStatus === 'fail' ? 1 : 0)
        })
    }
})

describe('stack depth check', () => {
    for (const { name, prNumber = EXEMPT_THROUGH_PR + 1, unavailable = false, expected } of [
        { name: 'fails a sixth open layer', expected: 1 },
        { name: 'keeps existing pull requests exempt', prNumber: EXEMPT_THROUGH_PR, unavailable: true, expected: 0 },
        { name: 'fails when GitHub cannot verify the stack', unavailable: true, expected: 1 },
    ]) {
        it(name, (t) => {
            const stack = {
                pull_requests: Array.from({ length: 6 }, (_, i) => ({ number: prNumber - 5 + i, state: 'open' })),
            }
            const result = runWithFakeGh(t, unavailable ? null : stack, [], {
                GITHUB_REPOSITORY: 'example/repository',
                PR_NUMBER: String(prNumber),
                STACK_NUMBER: '123',
            })
            assert.equal(result.error, undefined)
            assert.equal(result.status, expected, result.stdout + result.stderr)
        })
    }
})
