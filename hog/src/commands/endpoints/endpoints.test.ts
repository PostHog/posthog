import { describe, expect, test } from 'bun:test'
import { z } from 'zod'

import { runHog, TEST_CREDENTIALS } from '@/testing'

import { pushPlanLines } from './push'

const AGENT = { ...TEST_CREDENTIALS, CLAUDECODE: '1' }
const BASE = 'https://ph.example.com/api/environments/7/'

const endpoint = (
    name: string,
    query: Record<string, unknown>,
    extra: Record<string, unknown> = {}
): Record<string, unknown> => ({
    id: `id-${name}`,
    name,
    description: '',
    query,
    is_active: true,
    is_materialized: false,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ui_url: `https://ph.example.com/project/7/endpoints/${name}`,
    ...extra,
})

// A trends endpoint as PostHog returns it: nulls for unset fields, variables keyed by ID, and a
// refresh interval kept after materialization was turned off.
const TRENDS = endpoint(
    'weekly',
    {
        kind: 'TrendsQuery',
        interval: 'week',
        series: [{ kind: 'EventsNode', event: 'signed_up', math: null }],
        tags: null,
    },
    { data_freshness_seconds: 86400, description: 'Weekly signups' }
)
const HOGQL = endpoint('by-type', {
    kind: 'HogQLQuery',
    query: 'SELECT count()\r\nFROM events\r\nWHERE event = {variables.event_type}',
    variables: { 'var-1': { variableId: 'var-1', code_name: 'event_type', value: '$pageview' } },
})
// PostHog allows a variable without a code name, which no endpoint can use.
const VARIABLES = [
    { id: 'var-1', name: 'event_type', code_name: 'event_type', type: 'String' },
    { id: 'var-0', name: 'Old variable', code_name: null, type: 'String' },
]

function server(endpoints: unknown[], extra: (url: string, body: unknown) => unknown = () => undefined) {
    return (url: string, body: unknown) => {
        const reply = extra(url, body)
        if (reply) {
            return reply as { status: number; body: unknown; headers?: Record<string, string> }
        }
        if (url.replace(/\?.*/, '') === `${BASE}endpoints/`) {
            return { status: 200, body: { results: endpoints } }
        }
        if (url === `${BASE}insight_variables/`) {
            return { status: 200, body: { results: VARIABLES } }
        }
        return { status: 404, body: { detail: 'Not found.' } }
    }
}

const PULLED_WEEKLY =
    'name: weekly\ndescription: Weekly signups\nquery_definition:\n  kind: TrendsQuery\n  interval: week\n  series:\n    - kind: EventsNode\n      event: signed_up\n'

const PULLED_BY_TYPE = `# by-type.yaml
name: by-type
query: |-
  SELECT count()
  FROM events
  WHERE event = {variables.event_type}
variables:
  - name: event_type
    type: String
    default: $pageview
`

describe('hog endpoints', () => {
    test.each([
        ['', BASE],
        ['under a path', 'https://ph.example.com/posthog/api/environments/7/'],
    ])('list reads one page and gives agents the next offset, for a host %s', async (_name, base) => {
        const result = await runHog(['endpoints', 'list', '--limit', '1', '--offset', '1'], {
            env: { ...AGENT, HOG_HOST: new URL('../../../', base).toString() },
            respond: (url) =>
                url === `${base}endpoints/?limit=1&offset=1`
                    ? { status: 200, body: { count: 3, results: [HOGQL], next: `${base}endpoints/?limit=1&offset=2` } }
                    : { status: 404, body: {} },
        })

        expect(result.requests).toHaveLength(1)
        expect(result.json()).toMatchObject({ endpoints: [{ name: 'by-type' }], count: 3, nextOffset: 2 })
    })

    test('list tells a person the command for the next page', async () => {
        const result = await runHog(['endpoints', 'list', '--limit', '1'], {
            stdoutIsTTY: true,
            env: TEST_CREDENTIALS,
            respond: () => ({
                status: 200,
                body: { count: 2, results: [TRENDS], next: `${BASE}endpoints/?limit=1&offset=1` },
            }),
        })

        expect(result.stdout).toContain('Endpoints 1-1 of 2 in project 7')
        expect(result.stdout).toContain('Run hog endpoints list --offset 1 --limit 1 for the next page.')
    })

    test.each([
        ['stops at the page that holds every local name', false, [`${BASE}endpoints/`]],
        [
            'looks names up one by one in a project too large to read',
            true,
            [...Array.from({ length: 20 }, () => `${BASE}endpoints/`), `${BASE}endpoints/weekly/`],
        ],
    ])('diff %s', async (_name, endless, expectedUrls) => {
        const result = await runHog(['endpoints', 'diff', 'weekly.yaml'], {
            env: AGENT,
            files: { '/work/weekly.yaml': PULLED_WEEKLY },
            respond: (url) =>
                url === `${BASE}endpoints/weekly/`
                    ? { status: 200, body: TRENDS }
                    : {
                          status: 200,
                          body: { results: endless ? [HOGQL] : [TRENDS], next: `${BASE}endpoints/?offset=1` },
                      },
        })

        expect(result.exitCode).toBe(0)
        expect(result.requests.map((request) => request.url.replace(/\?.*/, ''))).toEqual(expectedUrls)
    })

    test('pull --all fails instead of pulling part of a project too large to read', async () => {
        const result = await runHog(['endpoints', 'pull', '--all', '--yes'], {
            env: AGENT,
            respond: () => ({ status: 200, body: { results: [TRENDS], next: `${BASE}endpoints/?offset=1` } }),
        })

        expect(result.error()).toMatchObject({ code: 'list_too_long' })
        expect(result.files).toEqual({})
    })

    test('pull refuses a pagination link to another host, so the token stays on the host', async () => {
        const result = await runHog(['endpoints', 'pull', '--all', '--dry-run'], {
            env: AGENT,
            respond: () => ({
                status: 200,
                body: { results: [TRENDS], next: 'https://ph.example.com//attacker.example/endpoints/' },
            }),
        })

        expect(result.error()).toMatchObject({ code: 'unexpected_response' })
        expect(result.requests.map((request) => new URL(request.url).host)).toEqual(['ph.example.com'])
    })

    test('pull writes short files with the project variable types, and updates a file in place', async () => {
        const result = await runHog(['endpoints', 'pull', '--all', '--yes'], {
            env: AGENT,
            files: {
                '/work/posthog.json': JSON.stringify({ endpoints: { dir: 'endpoints' } }),
                '/work/endpoints/signups.yaml': 'name: weekly\nquery_definition:\n  kind: TrendsQuery\n',
            },
            respond: server([TRENDS, HOGQL]),
        })
        expect(result.exitCode).toBe(0)
        expect(result.files['/work/endpoints/by-type.yaml']).toBe(PULLED_BY_TYPE)
        expect(result.files['/work/endpoints/signups.yaml']).toBe(`# signups.yaml\n${PULLED_WEEKLY}`)
        expect(result.files['/work/endpoints/weekly.yaml']).toBeUndefined()
    })

    test('pull takes variable types from the values when the key cannot read project variables', async () => {
        const result = await runHog(['endpoints', 'pull', 'by-type', '--yes'], {
            env: AGENT,
            respond: server([HOGQL], (url) =>
                url === `${BASE}insight_variables/` ? { status: 403, body: { detail: 'Forbidden' } } : undefined
            ),
        })

        expect(result.exitCode).toBe(0)
        expect(result.files['/work/by-type.yaml']).toBe(PULLED_BY_TYPE.replace('type: String', 'type: string'))
    })

    test.each([
        ['finds a variable on a late page by paging, without a request per variable', 25, 200, 'String', false],
        ['fetches a variable past the page cap by its ID', null, 200, 'String', true],
        ['takes the type from the value when the variable was deleted', null, 404, 'string', true],
    ])('pull %s', async (_name, foundOnPage, detailStatus, type, fetchesById) => {
        const result = await runHog(['endpoints', 'pull', 'by-type', '--yes'], {
            env: AGENT,
            respond: server([HOGQL], (url) => {
                if (url === `${BASE}insight_variables/var-1/`) {
                    return {
                        status: detailStatus,
                        body: detailStatus === 200 ? VARIABLES[0] : { detail: 'Not found.' },
                    }
                }
                if (!url.startsWith(`${BASE}insight_variables/`)) {
                    return undefined
                }
                const page = Number(new URL(url).searchParams.get('page') ?? '1')
                const results = page === foundOnPage ? [VARIABLES[0]] : []
                return { status: 200, body: { results, next: `${BASE}insight_variables/?page=${page + 1}` } }
            }),
        })

        expect(result.exitCode).toBe(0)
        expect(result.files['/work/by-type.yaml']).toBe(PULLED_BY_TYPE.replace('type: String', `type: ${type}`))
        expect(result.requests.some((request) => request.url.endsWith('/insight_variables/var-1/'))).toBe(fetchesById)
    })

    test.each([
        [
            'a file that defines another endpoint',
            { '/work/weekly.yaml': 'name: by-type\nquery: SELECT 1\n' },
            { '/work/weekly.yaml': PULLED_BY_TYPE.replace('# by-type.yaml', '# weekly.yaml') },
        ],
        [
            'a file hog cannot read',
            { '/work/weekly.yaml': 'name: weekly\nquery: [unclosed\n' },
            { '/work/weekly.yaml': 'name: weekly\nquery: [unclosed\n' },
        ],
    ])('pull never overwrites %s with another endpoint', async (_name, files, expected) => {
        const result = await runHog(['endpoints', 'pull', '--all', '--yes'], {
            env: AGENT,
            files,
            respond: server([TRENDS, HOGQL]),
        })
        expect(result.exitCode).toBe(1)
        expect(result.files).toMatchObject(expected)
        expect(result.json()).toMatchObject({ problems: [expect.objectContaining({ path: 'weekly.yaml' })] })
    })

    test.each([
        ['files that match PostHog', { 'by-type.yaml': PULLED_BY_TYPE }, 0, []],
        [
            'a changed query',
            { 'by-type.yaml': PULLED_BY_TYPE.replace('count()', 'count(*)') },
            1,
            [{ name: 'by-type', action: 'update', fields: ['query'] }],
        ],
        [
            // The file posthog-cli writes, with the lowercase type it infers from the default.
            'a posthog-cli file',
            { 'by-type.yaml': PULLED_BY_TYPE.replace('type: String', 'type: string') },
            0,
            [],
        ],
        [
            // PostHog keeps the refresh interval of an endpoint that is no longer materialized.
            'materialization turned off on both sides',
            { 'weekly.yaml': `${PULLED_WEEKLY}materialization:\n  enabled: false\n  schedule: 1hour\n` },
            0,
            [],
        ],
        [
            'a changed default',
            { 'by-type.yaml': PULLED_BY_TYPE.replace('default: $pageview', 'default: $autocapture') },
            1,
            [{ name: 'by-type', action: 'update', fields: ['defaults'] }],
        ],
        ['a file with a typo', { 'by-type.yaml': `${PULLED_BY_TYPE}descripton: oops\n` }, 1, []],
    ])('diff with %s', async (_name, files, exitCode, changed) => {
        const result = await runHog(['endpoints', 'diff'], {
            env: AGENT,
            files: {
                '/work/posthog.json': JSON.stringify({ endpoints: { dir: 'endpoints' } }),
                ...Object.fromEntries(Object.entries(files).map(([name, text]) => [`/work/endpoints/${name}`, text])),
            },
            respond: server([TRENDS, HOGQL]),
        })
        expect(result.exitCode).toBe(exitCode)
        const { plan } = result.json(
            z.object({
                plan: z.array(
                    z.object({
                        name: z.string(),
                        action: z.string(),
                        changes: z.array(z.object({ field: z.string() })),
                    })
                ),
            })
        )
        expect(
            plan
                .filter((item) => item.action !== 'skip')
                .map((item) => ({ name: item.name, action: item.action, fields: item.changes.map((c) => c.field) }))
        ).toEqual(changed)
    })

    test('pull escapes terminal control characters in the PostHog side of a preview', async () => {
        const edited = { ...TRENDS, description: '\u001b]52;c;eA==\u0007Weekly signups' }

        const result = await runHog(['endpoints', 'pull', 'weekly', '--dry-run'], {
            stdoutIsTTY: true,
            env: { ...TEST_CREDENTIALS, NO_COLOR: '1' },
            files: { '/work/weekly.yaml': PULLED_WEEKLY },
            respond: server([edited]),
        })

        expect(result.stdout).toContain('\\x1b]52;c;eA==\\x07Weekly signups')
        expect(result.stdout).not.toContain('\u001b')
    })

    test('push previews escape variable names and rejection reasons from PostHog', () => {
        const name = '\u001b]52;c;eA==\u0007x'
        const item = {
            name: 'weekly',
            path: 'weekly.yaml',
            action: 'skip' as const,
            reason: `${name} is used by the query`,
            changes: [],
            variables: [
                { name, change: 'remove' as const },
                { name, change: 'retype' as const, type: 'String', from: 'Number' },
            ],
        }

        const lines = pushPlanLines([item], (text) => text).join('\n')

        expect(lines).toContain('\\x1b]52;c;eA==\\x07x')
        expect(lines).not.toContain('\u001b')
    })

    test('push asks agents for --yes before it changes anything', async () => {
        const result = await runHog(['endpoints', 'push', 'new.yaml'], {
            env: AGENT,
            files: { '/work/new.yaml': 'name: new\nquery: SELECT 1\n' },
            respond: server([]),
        })
        expect(result.error().code).toBe('confirmation_required')
        expect(result.requests.filter((request) => request.method !== 'GET')).toEqual([])
    })

    test('push stops with the step-up details when PostHog refuses a write for a missing scope', async () => {
        const result = await runHog(['endpoints', 'push', 'new.yaml', '--yes'], {
            env: AGENT,
            files: { '/work/new.yaml': 'name: new\nquery: SELECT 1\n' },
            respond: server([], (url, body) =>
                url === `${BASE}endpoints/` && body
                    ? {
                          status: 403,
                          body: { detail: 'missing scope' },
                          headers: { 'WWW-Authenticate': 'Bearer error="insufficient_scope", scope="endpoint:write"' },
                      }
                    : undefined
            ),
        })
        expect(result.error()).toMatchObject({ code: 'step_up_required', scopes: ['endpoint:write'] })
    })

    test.each([
        ['outside CI shows', {}, 'PostHog answered with HTTP 400: An endpoint with this name already exists.'],
        [
            'in CI hides',
            { CI: 'true' },
            "PostHog answered with HTTP 400. PostHog's reason is hidden in CI. Run the command outside CI to see it.",
        ],
    ])("push of an endpoint PostHog refuses %s PostHog's reason in its outcome", async (_name, env, error) => {
        const result = await runHog(['endpoints', 'push', 'new.yaml', '--yes'], {
            env: { ...AGENT, ...env },
            files: { '/work/new.yaml': 'name: new\nquery: SELECT 1\n' },
            respond: server([], (url, body) =>
                url === `${BASE}endpoints/` && body
                    ? {
                          status: 400,
                          body: { type: 'validation_error', detail: 'An endpoint with this name already exists.' },
                      }
                    : undefined
            ),
        })

        expect(result.json()).toMatchObject({ outcomes: [{ name: 'new', status: 'failed', error }] })
    })

    test.each([{}, { CI: 'true' }])('push omits response values when decoding fails with env %j', async (env) => {
        const result = await runHog(['endpoints', 'push', 'new.yaml', '--yes'], {
            env: { ...AGENT, ...env },
            files: { '/work/new.yaml': 'name: new\nquery: SELECT 1\n' },
            respond: server([], (url, body) =>
                url === `${BASE}endpoints/` && body
                    ? {
                          status: 201,
                          body: endpoint(
                              'new',
                              { kind: 'HogQLQuery', query: 'SELECT 1' },
                              { is_active: 'SYNTHETIC_RESPONSE_VALUE' }
                          ),
                      }
                    : undefined
            ),
        })

        expect(result.exitCode).toBe(1)
        expect(result.json()).toMatchObject({
            outcomes: [{ status: 'failed', error: expect.stringContaining('is_active') }],
        })
        expect(result.stdout).not.toContain('SYNTHETIC_RESPONSE_VALUE')
        expect(result.stderr).not.toContain('SYNTHETIC_RESPONSE_VALUE')
    })

    test('push creates the variables a file needs, then the endpoint, and skips files PostHog would reject', async () => {
        const result = await runHog(['endpoints', 'push', 'endpoints', '--yes'], {
            env: AGENT,
            files: {
                '/work/endpoints/a.yaml': [
                    'name: by-country',
                    'query: SELECT count() FROM events WHERE properties.$geoip_country_code = {variables.country} AND properties.region IN {variables.regions}',
                    'variables:',
                    '  - name: country',
                    // posthog-cli writes lowercase types, and PostHog only accepts its own names.
                    '    type: string',
                    '    default: US',
                    '  - name: regions',
                    '    type: array',
                    '    default: [eu, us]',
                    'materialization:',
                    '  enabled: true',
                    '  schedule: 1hour',
                ].join('\n'),
                '/work/endpoints/b.yaml':
                    'name: unused\nquery: SELECT 1\nvariables:\n  - name: extra\n    type: String\n',
            },
            respond: server([], (url, body) =>
                url === `${BASE}insight_variables/` && body
                    ? {
                          status: 201,
                          body:
                              (body as { code_name: string }).code_name === 'country'
                                  ? { id: 'var-2', name: 'country', code_name: 'country', type: 'String' }
                                  : {
                                        id: 'var-3',
                                        name: 'regions',
                                        code_name: 'regions',
                                        type: 'List',
                                        is_multi: true,
                                    },
                      }
                    : url === `${BASE}endpoints/` && body
                      ? { status: 201, body: { ...endpoint('by-country', {}), ui_url: 'https://ph.example.com/e' } }
                      : undefined
            ),
        })
        expect(result.exitCode).toBe(1)
        expect(result.requests.filter((request) => request.method === 'POST').map((request) => request.body)).toEqual([
            { name: 'country', code_name: 'country', type: 'String', default_value: 'US' },
            // An array default makes a multiple-selection list, or PostHog keeps only its first value.
            { name: 'regions', code_name: 'regions', type: 'List', default_value: ['eu', 'us'], is_multi: true },
            {
                name: 'by-country',
                description: '',
                query: {
                    kind: 'HogQLQuery',
                    query: 'SELECT count() FROM events WHERE properties.$geoip_country_code = {variables.country} AND properties.region IN {variables.regions}',
                    variables: {
                        'var-2': { variableId: 'var-2', code_name: 'country', value: 'US' },
                        'var-3': { variableId: 'var-3', code_name: 'regions', value: ['eu', 'us'] },
                    },
                },
                is_materialized: true,
                data_freshness_seconds: 3600,
            },
        ])
        expect(result.json()).toMatchObject({
            outcomes: [{ name: 'by-country', status: 'created' }],
            plan: [{}, { name: 'unused', action: 'skip', invalid: true, reason: expect.stringContaining('extra') }],
        })
    })

    test.each([
        ['neither a name nor --file', ['endpoints', 'run'], 'usage_error'],
        ['a name and --file', ['endpoints', 'run', 'x', '--file', 'x.yaml'], 'usage_error'],
        ['a variable without a value', ['endpoints', 'run', 'x', '--var', 'country'], 'invalid_variable'],
    ])('run refuses %s', async (_name, argv, code) => {
        const result = await runHog(argv, { env: AGENT })
        expect(result.exitCode).toBe(2)
        expect(result.error().code).toBe(code)
    })

    test('run passes every --var to the endpoint', async () => {
        const result = await runHog(['endpoints', 'run', 'by-type', '--var', 'a=1', '--var', 'b=x=y'], {
            env: AGENT,
            respond: () => ({ status: 200, body: { columns: ['total'], results: [[3]] } }),
        })
        expect(result.requests[0]).toMatchObject({
            url: `${BASE}endpoints/by-type/run/`,
            body: { variables: { a: '1', b: 'x=y' } },
        })
        expect(result.stdout).toBe('[3]\n')
    })

    test('run --file puts variables in the query with their project IDs, and falls back to the file defaults', async () => {
        const result = await runHog(['endpoints', 'run', '--file', 'by-type.yaml', '--var', 'limit=5'], {
            env: AGENT,
            files: {
                '/work/by-type.yaml': `${PULLED_BY_TYPE.replace('count()', 'count() LIMIT {variables.limit}')}  - name: limit\n    type: Number\n`,
            },
            respond: server([], (url) =>
                url === `${BASE}insight_variables/`
                    ? {
                          status: 200,
                          body: {
                              results: [
                                  ...VARIABLES,
                                  { id: 'var-9', name: 'limit', code_name: 'limit', type: 'Number' },
                              ],
                          },
                      }
                    : url === `${BASE}query/`
                      ? { status: 200, body: { columns: ['n'], results: [[1]] } }
                      : undefined
            ),
        })
        expect(result.exitCode).toBe(0)
        expect(result.requests.at(-1)!.body).toMatchObject({
            query: {
                kind: 'HogQLQuery',
                variables: {
                    'var-1': { variableId: 'var-1', code_name: 'event_type', value: '$pageview' },
                    'var-9': { variableId: 'var-9', code_name: 'limit', value: '5' },
                },
            },
        })
        expect(result.requests.at(-1)!.body).not.toHaveProperty('variables')
    })
})
