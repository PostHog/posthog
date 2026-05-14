import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import { describe, it } from 'node:test'

const INDEX_TS = resolve(dirname(fileURLToPath(import.meta.url)), 'index.ts')

function runCli(args: string[]): { status: number | null; stdout: string; stderr: string } {
    const result = spawnSync('node', ['--import', 'tsx', INDEX_TS, ...args], {
        encoding: 'utf8',
        env: { ...process.env, FORCE_COLOR: '0', NO_COLOR: '1' },
    })
    return { status: result.status, stdout: result.stdout, stderr: result.stderr }
}

describe('CLI bare invocations are friendly (gh-style)', () => {
    const friendlyCases: Array<{ name: string; args: string[]; expectedInOutput: string }> = [
        { name: '`ph` with no args prints usage', args: [], expectedInOutput: 'ph <command> [options]' },
        { name: '`ph auth` prints subcommands', args: ['auth'], expectedInOutput: 'Authentication commands' },
        { name: '`ph insights` prints subcommands', args: ['insights'], expectedInOutput: 'Manage insights' },
        { name: '`ph dashboards` prints subcommands', args: ['dashboards'], expectedInOutput: 'Manage dashboards' },
        { name: '`ph feature-flags` prints subcommands', args: ['feature-flags'], expectedInOutput: 'Manage feature-flags' },
    ]

    for (const { name, args, expectedInOutput } of friendlyCases) {
        it(`${name}: exits 0 and shows help`, () => {
            const { status, stdout, stderr } = runCli(args)
            const combined = stdout + stderr
            assert.equal(status, 0, `expected exit 0, got ${status}. output:\n${combined}`)
            assert.ok(
                combined.includes(expectedInOutput),
                `expected output to contain "${expectedInOutput}". got:\n${combined}`
            )
            assert.ok(
                !combined.includes('You need at least one command'),
                `expected no demandCommand error message. got:\n${combined}`
            )
            assert.ok(
                !combined.includes('You need to specify a subcommand'),
                `expected no demandCommand error message. got:\n${combined}`
            )
        })
    }
})

describe('CLI invalid invocations still error', () => {
    const errorCases: Array<{ name: string; args: string[]; expectedInOutput: string }> = [
        { name: 'unknown top-level command', args: ['definitely-not-a-real-command'], expectedInOutput: 'Unknown command' },
        { name: 'unknown subcommand', args: ['insights', 'definitely-not-a-real-subcommand'], expectedInOutput: 'Unknown command' },
    ]

    for (const { name, args, expectedInOutput } of errorCases) {
        it(`${name}: exits 1 with error`, () => {
            const { status, stdout, stderr } = runCli(args)
            const combined = stdout + stderr
            assert.equal(status, 1, `expected exit 1, got ${status}. output:\n${combined}`)
            assert.ok(
                combined.includes(expectedInOutput),
                `expected output to contain "${expectedInOutput}". got:\n${combined}`
            )
        })
    }
})
