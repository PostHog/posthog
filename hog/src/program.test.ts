import { describe, expect, test } from 'bun:test'

import pkg from '../package.json' with { type: 'json' }
import { COMMANDS } from './catalog'
import { run } from './program'
import { fakeRuntime } from './test-runtime'

const CREDENTIALS = {
    POSTHOG_CLI_API_KEY: 'phx_test',
    POSTHOG_CLI_PROJECT_ID: '7',
    POSTHOG_CLI_HOST: 'https://ph.example.com',
    NO_COLOR: '1',
}
const ROWS = {
    columns: ['event', 'total'],
    results: [
        ['$pageview', 70],
        ['signup', null],
    ],
    hasMore: false,
}

describe('hog', () => {
    test.each([
        ['no arguments prints help', [], 'Usage: hog'],
        ['--version prints the version', ['--version'], pkg.version],
        ['help for a ported command prints its usage', ['help', 'query', 'run'], 'Usage: hog query run'],
    ])('%s', async (_name, argv, stdout) => {
        const runtime = fakeRuntime({})
        expect(await run(argv, runtime)).toBe(0)
        expect(runtime.stdout()).toContain(stdout)
    })

    test.each(COMMANDS.filter((command) => !command.available).map((command) => [command.name, command.legacyCommand]))(
        '%s fails and points to %s',
        async (name, legacyCommand) => {
            const runtime = fakeRuntime({})
            expect(await run([name, 'sub', "it's", '--flag'], runtime)).toBe(1)
            const { error } = JSON.parse(runtime.stderr())
            expect(error.code).toBe('not_ported')
            expect(error.message).toContain(`${legacyCommand} sub 'it'\\''s' --flag`)
        }
    )

    test('help for an unported command points to its posthog-cli help', async () => {
        const runtime = fakeRuntime({})
        expect(await run(['help', 'dsym', 'upload'], runtime)).toBe(1)
        expect(JSON.parse(runtime.stderr()).error.message).toContain('posthog-cli dsym upload --help')
    })

    test('an unknown command is a usage error, reported as JSON to agents', async () => {
        const runtime = fakeRuntime({ env: { CLAUDECODE: '1' } })
        expect(await run(['nope'], runtime)).toBe(2)
        expect(JSON.parse(runtime.stderr())).toMatchObject({ error: { code: 'unknown_command' } })
    })

    test.each([
        [
            'a pipe gets one JSON array per row',
            false,
            ['query', 'run', 'select 1'],
            '["$pageview",70]\n["signup",null]\n',
        ],
        ['a terminal gets a table', true, ['query', 'run', 'select 1'], '$pageview     70\nsignup      null\n2 rows\n'],
    ])('query run: %s', async (_name, tty, argv, expected) => {
        const runtime = fakeRuntime({
            env: CREDENTIALS,
            stdoutIsTTY: tty,
            respond: () => ({ status: 200, body: ROWS }),
        })
        expect(await run(argv, runtime)).toBe(0)
        expect(runtime.stdout()).toEndWith(expected)
        expect(runtime.requests).toEqual([
            {
                url: 'https://ph.example.com/api/environments/7/query',
                body: { query: { kind: 'HogQLQuery', query: 'select 1' }, refresh: 'blocking' },
            },
        ])
    })

    test('query run reads the query from stdin when it is -', async () => {
        const runtime = fakeRuntime({
            env: CREDENTIALS,
            stdin: 'select 2',
            respond: () => ({ status: 200, body: ROWS }),
        })
        expect(await run(['query', 'run', '-'], runtime)).toBe(0)
        expect(runtime.requests[0]?.body).toMatchObject({ query: { query: 'select 2' } })
    })

    test('query run reports the API error code and exits 1', async () => {
        const runtime = fakeRuntime({
            env: CREDENTIALS,
            respond: () => ({
                status: 400,
                body: { type: 'validation_error', code: 'hogql_query_error', detail: 'Unable to resolve field: nope' },
            }),
        })
        expect(await run(['query', 'run', 'select nope from events'], runtime)).toBe(1)
        expect(JSON.parse(runtime.stderr())).toMatchObject({
            error: { code: 'hogql_query_error', message: 'Unable to resolve field: nope' },
        })
    })

    test.each([
        ['a valid query exits 0', { isValid: true, errors: [], warnings: [], notices: [] }, 0, 'Query is valid'],
        [
            'a query with errors exits 1 and points at the error',
            { isValid: false, errors: [{ message: 'expected ), got Ident', start: 7, end: 11 }] },
            1,
            '  1 | select from\n             ^^^^',
        ],
    ])('query check: %s', async (_name, body, code, expected) => {
        const runtime = fakeRuntime({ env: CREDENTIALS, stdoutIsTTY: true, respond: () => ({ status: 200, body }) })
        expect(await run(['query', 'check', 'select from', '-o', 'text'], runtime)).toBe(code)
        expect(runtime.stdout()).toContain(expected)
    })

    test('commands lists every command for agents', async () => {
        const runtime = fakeRuntime({ env: { CLAUDECODE: '1' } })
        expect(await run(['commands'], runtime)).toBe(0)
        const manifest = JSON.parse(runtime.stdout())
        const names = manifest.commands.map((command: { name: string }) => command.name)
        expect(manifest.agent).toBe('claude-code')
        expect(names).toEqual([
            'query run',
            'query check',
            ...COMMANDS.filter((command) => !command.available).map((command) => command.name),
        ])
    })
})
