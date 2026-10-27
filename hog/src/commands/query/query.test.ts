import { describe, expect, test } from 'bun:test'
import { styleText } from 'node:util'

import { runHog, TEST_CREDENTIALS } from '@/testing'

const ROWS = {
    columns: ['event', 'total'],
    results: [
        ['$pageview', 70],
        ['signup', null],
    ],
    hasMore: false,
}

describe('hog query', () => {
    test.each([
        ['a pipe gets one JSON array per row', false, [], '["$pageview",70]\n["signup",null]\n'],
        [
            'a terminal gets a table with numbers on the right',
            true,
            [],
            '│ $pageview │    70 │\n│ signup    │  null │\n└───────────┴───────┘\n2 rows\n',
        ],
        [
            '--raw prints the full response',
            false,
            ['--raw'],
            '{"columns":["event","total"],"hasMore":false,"results":[["$pageview",70],["signup",null]]}\n',
        ],
    ])('run: %s', async (_name, tty, flags, expected) => {
        const result = await runHog(['query', 'run', 'select 1', ...flags], {
            env: TEST_CREDENTIALS,
            stdoutIsTTY: tty,
            respond: () => ({ status: 200, body: ROWS }),
        })
        expect(result.exitCode).toBe(0)
        expect(result.stdout).toEndWith(expected)
        expect(result.requests).toEqual([
            {
                method: 'POST',
                url: 'https://ph.example.com/api/environments/7/query',
                body: { query: { kind: 'HogQLQuery', query: 'select 1' }, refresh: 'blocking' },
            },
        ])
    })

    test('run fits the table to a narrow terminal', async () => {
        const long = { columns: ['event', 'properties'], results: [['$pageview', 'x'.repeat(200)]] }
        const result = await runHog(['query', 'run', 'select 1'], {
            env: TEST_CREDENTIALS,
            stdoutIsTTY: true,
            columns: 40,
            respond: () => ({ status: 200, body: long }),
        })
        const widths = result.stdout
            .trimEnd()
            .split('\n')
            .map((line) => Bun.stringWidth(line))
        expect(Math.max(...widths)).toBe(40)
        expect(result.stdout).toContain('│ $pageview │ xxx')
    })

    test('run colors values by their ClickHouse type', async () => {
        const typed = {
            columns: ['day', 'total'],
            types: [
                ['day', 'Nullable(DateTime64(6))'],
                ['total', 'UInt64'],
            ],
            results: [['2026-10-27 00:00:00', 70]],
        }
        const result = await runHog(['query', 'run', 'select 1'], {
            env: { ...TEST_CREDENTIALS, NO_COLOR: undefined },
            stdoutIsTTY: true,
            respond: () => ({ status: 200, body: typed }),
        })
        expect(result.stdout).toContain(styleText('magenta', '2026-10-27 00:00:00', { validateStream: false }))
        expect(result.stdout).toContain(styleText('cyan', '70', { validateStream: false }))
    })

    test('run reads the query from stdin when it is -', async () => {
        const result = await runHog(['query', 'run', '-'], {
            env: TEST_CREDENTIALS,
            stdin: 'select 2',
            respond: () => ({ status: 200, body: ROWS }),
        })
        expect(result.exitCode).toBe(0)
        expect(result.requests[0]?.body).toMatchObject({ query: { query: 'select 2' } })
    })

    test.each([
        [
            'a validation error points to query check',
            400,
            { type: 'validation_error', code: 'hogql_query_error', detail: 'Unable to resolve field: nope' },
            {
                code: 'hogql_query_error',
                message: 'Unable to resolve field: nope',
                hint: expect.stringContaining('hog query check'),
            },
        ],
        [
            'a 403 names the scope the command needs',
            403,
            { type: 'authentication_error', code: 'permission_denied', detail: 'No access' },
            { code: 'permission_denied', hint: expect.stringContaining('query:read') },
        ],
    ])('run: %s', async (_name, status, body, error) => {
        const result = await runHog(['query', 'run', 'select nope from events'], {
            env: TEST_CREDENTIALS,
            respond: () => ({ status, body }),
        })
        expect(result.exitCode).toBe(1)
        expect(result.error()).toMatchObject(error)
    })

    test.each([
        ['a valid query exits 0', { isValid: true, errors: [], warnings: [], notices: [] }, 0, 'Query is valid'],
        [
            'a query with errors exits 1 and points at the error',
            { isValid: false, errors: [{ message: 'expected ), got Ident', start: 7, end: 11 }] },
            1,
            '  1 | select from\n             ^^^^',
        ],
    ])('check: %s', async (_name, body, exitCode, expected) => {
        const result = await runHog(['query', 'check', 'select from', '-o', 'text'], {
            env: TEST_CREDENTIALS,
            stdoutIsTTY: true,
            respond: () => ({ status: 200, body }),
        })
        expect(result.exitCode).toBe(exitCode)
        expect(result.stdout).toContain(expected)
    })
})
