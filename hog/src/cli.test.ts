import { describe, expect, test } from 'bun:test'

import { LEGACY_COMMANDS } from '@/commands/legacy'
import { VERSION } from '@/version'

import { runHog } from './testing'

describe('hog', () => {
    test.each([
        ['no arguments prints help', [], 'Usage: hog'],
        ['--version prints the version', ['--version'], VERSION],
        ['help for a command prints its usage', ['help', 'query', 'run'], 'Usage: hog query run'],
        [
            'help after a global option still finds the command',
            ['-o', 'json', 'help', 'query', 'run'],
            'Usage: hog query run',
        ],
        [
            'command help lists examples and scopes',
            ['query', 'run', '--help'],
            'Needs a personal API key with: query:read',
        ],
    ])('%s', async (_name, argv, stdout) => {
        const result = await runHog(argv)
        expect(result.exitCode).toBe(0)
        expect(result.stdout).toContain(stdout)
    })

    test.each(Object.entries(LEGACY_COMMANDS).map(([name, command]) => [name, 'use' in command ? command.use : '']))(
        '%s fails and points to %s',
        async (name, use) => {
            const result = await runHog([name, 'sub', "it's", '--flag'])
            expect(result.exitCode).toBe(1)
            expect(result.error()).toMatchObject({ code: 'not_ported' })
            expect(result.error().message).toContain(`${use} sub 'it'\\''s' --flag`)
        }
    )

    test.each([
        ['help for an unported command', ['help', 'logs', 'import'], 'posthog-cli exp logs import --help'],
        ['an unported subcommand of a ported group', ['query', 'editor'], 'posthog-cli exp query editor'],
        [
            'hog globals that posthog-cli takes before the subcommand',
            ['-o', 'json', '--host', 'https://eu.example.com', 'logs', 'import', '--dotenv-file=p.env', '--dir', 'x'],
            'posthog-cli --host https://eu.example.com --dotenv-file p.env exp logs import --dir x',
        ],
        [
            'an --output that the legacy command owns',
            ['logs', 'import', '--output', './logs'],
            'posthog-cli exp logs import --output ./logs',
        ],
    ])('%s points to posthog-cli', async (_name, argv, invocation) => {
        const result = await runHog(argv)
        expect(result.exitCode).toBe(1)
        expect(result.error().message).toEndWith(`Run this instead:\n  ${invocation}`)
    })

    test.each([
        ['an unknown command', ['nope'], 'unknown_command'],
        ['a missing argument', ['query', 'run'], 'usage_error'],
        ['an invalid --output', ['query', 'run', 'select 1', '-o', 'yaml'], 'usage_error'],
    ])('%s is a usage error, reported as JSON to agents', async (_name, argv, code) => {
        const result = await runHog(argv, { env: { CLAUDECODE: '1' } })
        expect(result.exitCode).toBe(2)
        expect(result.error()).toMatchObject({ code })
    })

    test.each([
        ['login', 'Did you mean `hog auth login`?'],
        ['sourcemap', '`sourcemap` is `hog error-tracking inject|upload|process` in hog.'],
        ['exp', '`exp` is `hog query|endpoints|schema` in hog.'],
    ])('a command that moved, like %s, points to its new name', async (name, message) => {
        const result = await runHog([name, 'upload'])
        expect(result.exitCode).toBe(2)
        expect(result.error().message).toContain(message)
    })

    test('a person sees errors as text', async () => {
        const result = await runHog(['qury'], { stdoutIsTTY: true, env: { NO_COLOR: '1' } })
        expect(result.stderr).toBe(
            "Error: Unknown command 'qury'\n(Did you mean query?)\nRun `hog --help` to see the available commands.\n"
        )
    })

    test('commands lists every command for agents', async () => {
        const result = await runHog(['commands'], { env: { CLAUDECODE: '1' } })
        expect(result.exitCode).toBe(0)
        const manifest = result.json()
        expect(manifest).toMatchObject({ cli: 'hog', agent: 'claude-code', aliases: { et: 'error-tracking' } })
        expect(manifest.globalOptions).toContainEqual(expect.objectContaining({ flags: '-o, --output <format>' }))
        expect(manifest.commands.find((command: { name: string }) => command.name === 'query run')).toMatchObject({
            name: 'query run',
            arguments: [{ name: 'query', required: true, stdin: true }],
            scopes: ['query:read'],
        })
        expect(manifest.commands.map((command: { name: string }) => command.name)).toEqual([
            'auth login',
            'auth logout',
            'auth status',
            'query run',
            'query check',
            'query editor',
            'api groups',
            'api tools',
            'api search',
            'api info',
            'api schema',
            'api call',
            'api access',
            'api skill',
            'api agents-md',
            'error-tracking inject',
            'error-tracking clone',
            'error-tracking upload',
            'error-tracking process',
            'error-tracking release',
            'error-tracking download',
            'error-tracking extract',
            'endpoints list',
            'endpoints get',
            'endpoints open',
            'endpoints run',
            'endpoints push',
            'endpoints pull',
            'endpoints diff',
            'schema pull',
            'schema status',
            'config check',
            'config schema',
            'commands',
            ...Object.keys(LEGACY_COMMANDS),
        ])
    })
})
