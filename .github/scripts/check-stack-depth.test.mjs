import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, it } from 'node:test'
import { fileURLToPath } from 'node:url'

import { checkStackDepth } from './check-stack-depth.mjs'

const layers = (...states) => states.map((state, i) => ({ number: 120300 + i, state }))

describe('checkStackDepth', () => {
    for (const { name, stack, expectedDepth, expectedStatus } of [
        {
            name: 'rejects the sixth open layer',
            stack: layers('open', 'open', 'open', 'open', 'open', 'open'),
            expectedDepth: 6,
            expectedStatus: 'fail',
        },
        {
            name: 'skips merged layers below',
            stack: layers('closed', 'closed', 'closed', 'closed', 'open', 'open', 'open'),
            expectedDepth: 3,
            expectedStatus: 'pass',
        },
        {
            name: 'accepts five open layers',
            stack: layers('open', 'open', 'open', 'open', 'open'),
            expectedDepth: 5,
            expectedStatus: 'pass',
        },
        {
            name: 'keeps existing pull requests exempt',
            stack: layers('open', 'open', 'open', 'open', 'open', 'open').map((pr, i) => ({
                ...pr,
                number: 120286 + i,
            })),
            expectedDepth: 6,
            expectedStatus: 'pass',
        },
        {
            name: 'rejects adding an unpublished layer to an exempt stack',
            stack: [...Array.from({ length: 6 }, (_, i) => ({ number: 120286 + i, state: 'open' })), { state: 'open' }],
            expectedDepth: 7,
            expectedStatus: 'fail',
        },
    ]) {
        it(name, () => {
            const result = checkStackDepth(stack)
            assert.equal(result.depth, expectedDepth)
            assert.equal(result.status, expectedStatus)
        })
    }
})

describe('local stack adapter', () => {
    it('checks unpublished branches through the same evaluator', (t) => {
        const directory = mkdtempSync(join(tmpdir(), 'stack-depth-local-'))
        t.after(() => rmSync(directory, { recursive: true, force: true }))
        writeFileSync(
            join(directory, 'gh'),
            '#!/bin/sh\nprintf \'%s\' \'{"branches":[{"isMerged":false},{"isMerged":false},{"isMerged":false},{"isMerged":false},{"isMerged":false},{"isMerged":false}]}\'\n',
            { mode: 0o755 }
        )
        const result = spawnSync(
            process.execPath,
            [fileURLToPath(new URL('./check-stack-depth.mjs', import.meta.url)), '--local'],
            {
                env: { PATH: directory },
                encoding: 'utf-8',
                timeout: 5000,
            }
        )
        assert.equal(result.status, 1, result.stderr)
        assert.equal(JSON.parse(result.stdout).status, 'fail')
    })
})

describe('stack depth check', () => {
    for (const { name, prNumber = 120292, unavailable = false, expected } of [
        { name: 'fails a sixth open layer', expected: 1 },
        { name: 'keeps existing pull requests exempt', prNumber: 120291, unavailable: true, expected: 0 },
        { name: 'fails when GitHub cannot verify the stack', unavailable: true, expected: 1 },
    ]) {
        it(name, (t) => {
            const directory = mkdtempSync(join(tmpdir(), 'stack-depth-'))
            t.after(() => rmSync(directory, { recursive: true, force: true }))
            const eventPath = join(directory, 'event.json')
            writeFileSync(eventPath, JSON.stringify({ pull_request: { number: prNumber, stack: { number: 999 } } }))
            const stack = {
                pull_requests: Array.from({ length: 6 }, (_, i) => ({ number: prNumber - 5 + i, state: 'open' })),
            }
            const mockFetch = `
                globalThis.fetch = async (url) => {
                    if (${unavailable}) return new Response('', { status: 503 });
                    if (url.endsWith('/stacks/123')) return new Response(${JSON.stringify(JSON.stringify(stack))});
                    return new Response('', { status: 403 });
                };
            `
            const result = spawnSync(
                process.execPath,
                [
                    '--import',
                    `data:text/javascript,${encodeURIComponent(mockFetch)}`,
                    fileURLToPath(new URL('./check-stack-depth.mjs', import.meta.url)),
                ],
                {
                    env: {
                        GITHUB_TOKEN: 'test-token',
                        GITHUB_REPOSITORY: 'example/repository',
                        GITHUB_EVENT_PATH: eventPath,
                        STACK_NUMBER: '123',
                    },
                    encoding: 'utf-8',
                    timeout: 5000,
                }
            )
            assert.equal(result.error, undefined)
            assert.equal(result.status, expected, result.stdout + result.stderr)
        })
    }
})
