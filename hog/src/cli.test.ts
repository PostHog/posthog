import { describe, expect, test } from 'bun:test'

import pkg from '../package.json' with { type: 'json' }
import { run } from './cli'

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
            'an unported command fails and names posthog-cli',
            ['query'],
            1,
            '',
            'Use `posthog-cli exp query` until it is.',
        ],
    ] as const)('%s', (_name, argv, code, stdout, stderr) => {
        const result = capture(argv)
        expect(result.code).toBe(code)
        expect(result.stdout).toContain(stdout)
        expect(result.stderr).toContain(stderr)
    })
})
