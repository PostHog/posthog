import { describe, expect, test } from 'bun:test'

import pkg from '../package.json' with { type: 'json' }
import { run } from './cli'
import { COMMANDS } from './commands'

function capture(argv: readonly string[]): { code: number; stdout: string; stderr: string } {
    let stdout = ''
    let stderr = ''
    const code = run(argv, {
        stdout: (text) => (stdout += text),
        stderr: (text) => (stderr += text),
    })
    return { code, stdout, stderr }
}

describe('hog', () => {
    test.each([
        ['no arguments prints help', [], 0, 'Usage: hog <command>', ''],
        ['--version prints the version', ['--version'], 0, pkg.version, ''],
        ['an unknown command fails', ['nope'], 1, '', 'Unknown command: nope'],
        [
            'an unported command passes its arguments to posthog-cli, quoted',
            ['query', 'run', "select 'a' from events"],
            1,
            '',
            `posthog-cli exp query run 'select '\\''a'\\'' from events'`,
        ],
        [
            'help for an unported command points to its posthog-cli help',
            ['help', 'dsym', 'upload'],
            1,
            '',
            'posthog-cli dsym upload --help',
        ],
    ] as const)('%s', (_name, argv, code, stdout, stderr) => {
        const result = capture(argv)
        expect(result.code).toBe(code)
        expect(result.stdout).toContain(stdout)
        expect(result.stderr).toContain(stderr)
    })

    test.each(COMMANDS.map((command) => [command.name, command.legacyCommand]))(
        '%s fails and points to %s',
        (name, legacyCommand) => {
            const result = capture([name, '--some-flag'])
            expect(result.code).toBe(1)
            expect(result.stdout).toBe('')
            expect(result.stderr).toContain(`${legacyCommand} --some-flag`)
        }
    )
})
