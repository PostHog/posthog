import { describe, expect, test } from 'bun:test'
import { styleText } from 'node:util'

import { runHog, TEST_CREDENTIALS } from '@/testing'

const ROWS = {
    columns: ['event', 'total'],
    types: [
        ['event', 'String'],
        ['total', 'UInt64'],
    ],
    results: [
        ['$pageview', 70],
        ['signup', null],
    ],
    hasMore: false,
    clickhouse: 'SELECT 1',
}

const FIRST_ID = '0190f5b41d2a7000a8c13f6e2b9c7d10'
const SECOND_ID = '0190f5b4-1d2a-7000-8a1c-3f6e2b9c7d11'
const SECOND_QUERY = 'select 2'
const JOINED_ID = "nightly's:run#1"
const JOINED_QUERY = 'select 3'
const RESULTS: Record<string, unknown> = {
    [FIRST_ID]: ROWS,
    [SECOND_ID]: { ...ROWS, results: [['second', 1]] },
    [JOINED_ID]: { ...ROWS, results: [['joined', 1]] },
}

const statusUrl = (id: string): string => `https://ph.example.com/api/environments/7/query/${encodeURIComponent(id)}/`
type Reply = { status: number; body: unknown }

const running = (id: string): Reply => ({ status: 202, body: { query_status: { id, complete: false } } })

function slowQueries(polls: number, final?: Reply): (url: string, body: unknown) => Reply {
    const checks = new Map<string, number>()
    return (url: string, body: unknown) => {
        const id = Object.keys(RESULTS).find((candidate) => url === statusUrl(candidate))
        if (id === undefined) {
            const text = JSON.stringify(body)
            return running(text.includes(SECOND_QUERY) ? SECOND_ID : text.includes(JOINED_QUERY) ? JOINED_ID : FIRST_ID)
        }

        const count = (checks.get(id) ?? 0) + 1
        checks.set(id, count)
        if (count < polls) {
            return running(id)
        }
        return final ?? { status: 200, body: { query_status: { id, complete: true, results: RESULTS[id] } } }
    }
}

describe('hog query', () => {
    test('run fails on an answer of the wrong shape, and names every field that is wrong', async () => {
        const result = await runHog(['query', 'run', 'select 1'], {
            env: TEST_CREDENTIALS,
            respond: () => ({ status: 200, body: { columns: 5, results: 'not rows' } }),
        })

        expect(result.exitCode).toBe(1)
        expect(result.error()).toMatchObject({ code: 'unexpected_response' })
        expect(result.error().message).toContain('columns:')
        expect(result.error().message).toContain('results:')
    })

    test.each([
        [
            'a pipe gets one object with the columns, the rows and whether more are left',
            false,
            [],
            '{"columns":[{"name":"event","type":"String"},{"name":"total","type":"UInt64"}],"hasMore":false,"rows":[["$pageview",70],["signup",null]]}\n',
        ],
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
            '{"clickhouse":"SELECT 1","columns":["event","total"],"hasMore":false,"results":[["$pageview",70],["signup",null]],"types":[["event","String"],["total","UInt64"]]}\n',
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
                body: { query: { kind: 'HogQLQuery', query: 'select 1' }, refresh: 'async' },
            },
        ])
    })

    test('run keeps columns that share a name, and tells agents how to get rows PostHog cut off', async () => {
        const result = await runHog(['query', 'run', 'select a.id, b.id from a join b on a.id = b.id'], {
            env: TEST_CREDENTIALS,
            respond: () => ({ status: 200, body: { columns: ['id', 'id'], results: [[1, 2]], hasMore: true } }),
        })

        expect(result.exitCode).toBe(0)
        expect(result.json()).toEqual({
            columns: [
                { name: 'id', type: null },
                { name: 'id', type: null },
            ],
            hasMore: true,
            hint: expect.stringContaining('Add a LIMIT'),
            rows: [[1, 2]],
        })
    })

    test.each([
        [
            'an agent gets the results of a query that finishes within the minute',
            'select 1',
            { stdoutIsTTY: false },
            3,
            '"rows":[["$pageview",70]',
        ],
        [
            'a person at a terminal waits for a query that runs past the minute',
            'select 1',
            { stdoutIsTTY: true },
            40,
            '│ $pageview │',
        ],
        [
            'a person who pipes the query into a terminal waits past the minute too',
            '-',
            { stdoutIsTTY: true, stdinIsTTY: false, stdin: 'select 1' },
            40,
            '│ $pageview │',
        ],
    ])('run: %s', async (_name, query, terminal, polls, expected) => {
        const result = await runHog(['query', 'run', query], {
            env: TEST_CREDENTIALS,
            ...terminal,
            respond: slowQueries(polls),
        })

        expect(result.exitCode).toBe(0)
        expect(result.stdout).toContain(expected)
        expect(result.requests.at(-1)?.url).toBe(statusUrl(FIRST_ID))
    })

    test('run returns a query still running after a minute, and --wait resumes it by its ID while another runs', async () => {
        const first = await runHog(['query', 'run', 'select 1'], {
            env: TEST_CREDENTIALS,
            respond: slowQueries(Infinity),
        })

        expect(first.exitCode).toBe(4)
        expect(first.json()).toEqual({
            status: 'running',
            queryId: FIRST_ID,
            next: `hog query run --wait ${FIRST_ID}`,
            hint: expect.stringContaining(`hog query run --wait ${FIRST_ID}`),
        })
        expect(first.elapsedMs).toBeLessThan(120_000)

        const second = await runHog(['query', 'run', SECOND_QUERY], {
            env: TEST_CREDENTIALS,
            respond: slowQueries(Infinity),
        })

        expect(second.exitCode).toBe(4)
        expect(second.json()).toMatchObject({ queryId: SECOND_ID, next: `hog query run --wait ${SECOND_ID}` })

        const resumed = await runHog(['query', 'run', '--wait', FIRST_ID], {
            env: TEST_CREDENTIALS,
            respond: slowQueries(2),
        })

        expect(resumed.exitCode).toBe(0)
        expect(resumed.json()).toMatchObject({ rows: ROWS.results, hasMore: false })
        expect(resumed.requests.map((request) => request.url)).toEqual([statusUrl(FIRST_ID), statusUrl(FIRST_ID)])
    })

    test('run quotes an ID another caller chose in the resume command, and --wait takes it back', async () => {
        const started = await runHog(['query', 'run', JOINED_QUERY], {
            env: TEST_CREDENTIALS,
            respond: slowQueries(Infinity),
        })

        expect(started.exitCode).toBe(4)
        expect(started.json()).toMatchObject({
            queryId: JOINED_ID,
            next: `hog query run --wait 'nightly'\\''s:run#1'`,
        })

        const resumed = await runHog(['query', 'run', '--wait', JOINED_ID], {
            env: TEST_CREDENTIALS,
            respond: slowQueries(1),
        })

        expect(resumed.exitCode).toBe(0)
        expect(resumed.json()).toMatchObject({ rows: [['joined', 1]] })
        expect(resumed.requests.map((request) => request.url)).toEqual([statusUrl(JOINED_ID)])
    })

    test.each([
        ['without an ID', ['--wait'], { code: 'usage_error', hint: expect.stringContaining('--wait <query-id>') }],
        ['with an ID that leaves the status path', ['--wait', '../../users/@me'], { code: 'invalid_input' }],
        ['with an ID that holds a space', ['--wait', 'a b'], { code: 'invalid_input' }],
        ['with a query as well', ['select 1', '--wait', FIRST_ID], { code: 'query_with_wait' }],
    ])('run --wait %s is a usage error that sends nothing', async (_name, flags, error) => {
        const result = await runHog(['query', 'run', ...flags], { env: TEST_CREDENTIALS, respond: slowQueries(1) })

        expect(result.exitCode).toBe(2)
        expect(result.error()).toMatchObject(error)
        expect(result.requests).toEqual([])
    })

    test.each([
        [
            'a query PostHog rejects keeps its reason',
            {
                status: 400,
                body: {
                    query_status: {
                        id: FIRST_ID,
                        complete: true,
                        error: true,
                        error_code: 'hogql_query_error',
                        error_message: 'Unable to resolve field: nope',
                    },
                },
            },
            { code: 'hogql_query_error', message: 'The query failed in PostHog: Unable to resolve field: nope' },
        ],
        [
            'a query PostHog no longer has says to run it again',
            { status: 404, body: { type: 'invalid_request', code: 'not_found', detail: 'Query not found' } },
            { code: 'query_expired', hint: expect.stringContaining('hog query run <query>') },
        ],
    ])('run --wait: %s', async (_name, final, error) => {
        const resumed = await runHog(['query', 'run', '--wait', FIRST_ID], {
            env: TEST_CREDENTIALS,
            respond: slowQueries(1, final),
        })

        expect(resumed.exitCode).toBe(1)
        expect(resumed.error()).toMatchObject(error)
    })

    test.each([
        [
            'a pipe keeps integers beyond the safe range exact',
            false,
            '{"columns":["n"],"results":[[18446744073709551615, 1.5]]}',
            '"rows":[[18446744073709551615,1.5]]',
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
            {},
            400,
            { type: 'validation_error', code: 'hogql_query_error', detail: 'Unable to resolve field: nope' },
            {
                code: 'hogql_query_error',
                message: 'PostHog answered with HTTP 400: Unable to resolve field: nope',
                hint: expect.stringContaining('hog query check'),
            },
        ],
        [
            'a field of another type keeps the rest of the error',
            {},
            400,
            { type: 'validation_error', code: null, detail: 'Unable to resolve field: nope' },
            {
                message: 'PostHog answered with HTTP 400: Unable to resolve field: nope',
                hint: expect.stringContaining('hog query check'),
            },
        ],
        [
            'a 403 names the scope the command needs',
            {},
            403,
            { type: 'authentication_error', code: 'permission_denied', detail: 'No access' },
            { code: 'permission_denied', hint: expect.stringContaining('query:read') },
        ],
        [
            "a validation error in CI leaves out PostHog's reason",
            { CI: 'true' },
            400,
            { type: 'validation_error', code: 'hogql_query_error', detail: 'Unable to resolve field: nope' },
            {
                code: 'hogql_query_error',
                message: 'PostHog answered with HTTP 400.',
                hint: expect.stringContaining('hidden in CI'),
            },
        ],
        [
            "a validation error on a CI service that doesn't set CI leaves out PostHog's reason",
            { JENKINS_URL: 'https://jenkins.example.com/' },
            400,
            { type: 'validation_error', code: 'hogql_query_error', detail: 'Unable to resolve field: nope' },
            { message: 'PostHog answered with HTTP 400.', hint: expect.stringContaining('hidden in CI') },
        ],
    ])('run: %s', async (_name, env, status, body, error) => {
        const result = await runHog(['query', 'run', 'select nope from events'], {
            env: { ...TEST_CREDENTIALS, ...env },
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
            '✗ Query has 1 error, 0 warnings, 0 notices\nerror: Query is too complex\n',
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
