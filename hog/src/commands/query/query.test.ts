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

    test.each([
        [
            'a pipe keeps integers beyond the safe range exact',
            false,
            '{"columns":["n"],"results":[[18446744073709551615, 1.5]]}',
            '[18446744073709551615,1.5]\n',
        ],
        [
            'a table keeps integers beyond the safe range exact',
            true,
            '{"columns":["n"],"results":[[18446744073709551615]]}',
            '│ 18446744073709551615 │',
        ],
        [
            'a table escapes terminal control characters in cells and headers',
            true,
            { columns: ['a\u001b[2J'], results: [['\u001b]52;c;eA==\u0007']] },
            '│ \\x1b]52;c;eA==\\x07 │',
        ],
    ])('run: %s', async (_name, tty, body, expected) => {
        const result = await runHog(['query', 'run', 'select 1'], {
            env: TEST_CREDENTIALS,
            stdoutIsTTY: tty,
            respond: () => ({ status: 200, body }),
        })
        expect(result.stdout).toContain(expected)
        expect(result.stdout).not.toContain('\u001b')
    })

    const tenColumns = Array.from({ length: 10 }, (_, index) => `column_${index}`)
    test.each([
        [
            'a long value',
            40,
            { columns: ['event', 'properties'], results: [['$pageview', 'x'.repeat(200)]] },
            '│ $pageview │ xxx',
        ],
        [
            'more columns than fit at the minimum width',
            80,
            { columns: tenColumns, results: [tenColumns.map((name) => `${name}_value`)] },
            '│ c',
        ],
    ])('run fits the table to a narrow terminal: %s', async (_name, columns, body, expected) => {
        const result = await runHog(['query', 'run', 'select 1'], {
            env: TEST_CREDENTIALS,
            stdoutIsTTY: true,
            columns,
            respond: () => ({ status: 200, body }),
        })
        const widths = result.stdout
            .trimEnd()
            .split('\n')
            .map((line) => Bun.stringWidth(line))
        expect(Math.max(...widths)).toBeLessThanOrEqual(columns)
        expect(result.stdout).toContain(expected)
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
        [
            'a valid query exits 0',
            'select from',
            { isValid: true, errors: [], warnings: [], notices: [] },
            0,
            'Query is valid',
        ],
        [
            'a query with errors exits 1 and points at the error',
            'select from',
            { isValid: false, errors: [{ message: 'expected ), got Ident', start: 7, end: 11 }] },
            1,
            '  1 | select from\n             ^^^^',
        ],
        [
            'offsets count code points, so an emoji earlier on does not shift the error',
            "select '😀',\nnope",
            { isValid: false, errors: [{ message: 'Unable to resolve field: nope', start: 12, end: 16 }] },
            1,
            '  2 | nope\n      ^^^^',
        ],
        [
            'an error at the very start of a multiline query points at line 1',
            'nope\nselect 1',
            { isValid: false, errors: [{ message: 'Unable to resolve field: nope', start: 0, end: 4 }] },
            1,
            '  --> line 1, column 1\n  1 | nope\n      ^^^^',
        ],
        [
            'a diagnostic without a location prints no source line',
            'select 1',
            { isValid: false, errors: [{ message: 'Query is too complex', start: null, end: null }] },
            1,
            'error: Query is too complex\n1 error',
        ],
        [
            'terminal escapes in the source and the message are printed escaped',
            'select \u001b]52;c;eA==\u0007',
            { isValid: false, errors: [{ message: 'bad \u001b[2J', start: 7, end: 8 }] },
            1,
            'error: bad \\x1b[2J\n  --> line 1, column 8\n  1 | select \\x1b]52;c;eA==\\x07\n             ^^^^',
        ],
    ])('check: %s', async (_name, query, body, exitCode, expected) => {
        const result = await runHog(['query', 'check', query, '-o', 'text'], {
            env: TEST_CREDENTIALS,
            stdoutIsTTY: true,
            respond: () => ({ status: 200, body }),
        })
        expect(result.exitCode).toBe(exitCode)
        expect(result.stdout).toContain(expected)
    })
})
