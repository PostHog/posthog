import { describe, expect, test } from 'bun:test'

import type {
    ApiCatalogDroppedTool,
    ApiConnection,
    ApiToolLibrary,
    ApiToolLibraryOptions,
    ApiToolResult,
    ApiToolSummary,
} from '@posthog/mcp/src/cli/library-types'

import { runHog, TEST_CREDENTIALS, type HogRun } from '@/testing'

const tool = (
    name: string,
    group: string,
    scopes: string[],
    kind: 'read' | 'write' | 'destructive'
): ApiToolSummary => ({
    name,
    title: name,
    summary: `Summary of ${name}`,
    description: `Description of ${name}`,
    group,
    feature: group,
    requiredScopes: scopes,
    readOnly: kind === 'read',
    destructive: kind === 'destructive',
    idempotent: kind === 'read',
    openWorld: true,
    requiresAiConsent: false,
})

const TOOLS = [
    tool('flag-list', 'Feature flags', ['feature_flag:read'], 'read'),
    tool('flag-delete', 'Feature flags', ['feature_flag:write'], 'destructive'),
    tool('insight-create', 'Insights & analytics', ['insight:write', 'query:read'], 'write'),
]

interface FakeLibrary extends ApiToolLibrary {
    calls: { tool: string; input: Record<string, unknown>; connection: ApiConnection; confirm: boolean }[]
}

interface FakeLibraryOptions {
    callResult?: ApiToolResult<unknown>
    scopedOrganizations?: string[]
    lookupFails?: boolean
}

function fakeLibrary(scopes: string[], options: FakeLibraryOptions = {}): FakeLibrary {
    const { callResult = { ok: true, value: { ok: 1 } }, scopedOrganizations = [], lookupFails = false } = options
    const calls: FakeLibrary['calls'] = []
    return {
        calls,
        tools: () => TOOLS,
        catalog: () => ({ source: 'bundled', build: null, tools: 0, dropped: [], rejected: null }),
        search: async (query) => ({
            names: TOOLS.filter((t) => t.name.includes(query)).map((t) => t.name),
            truncated: false,
        }),
        schema: async () => ({ type: 'object', properties: {} }),
        validate: (_name, input) =>
            'limit' in input && typeof input.limit !== 'number'
                ? { valid: false, error: 'parameter "limit" must be of type number' }
                : { valid: true, input },
        missingScopes: (granted, required) => required.filter((scope) => !granted.includes(scope)),
        keyAccess: async () =>
            lookupFails
                ? { ok: false, error: { code: 'api_error', message: 'Server error', status: 500 } }
                : { ok: true, value: { scopes, scopedTeams: [], scopedOrganizations } },
        call: async (name, input, connection, confirm) => {
            calls.push({ tool: name, input, connection, confirm })
            return callResult
        },
        flush: async () => {},
    }
}

describe('hog api', () => {
    test('groups count the tools the key can use', async () => {
        const result = await runHog(['api', 'groups'], {
            env: TEST_CREDENTIALS,
            apiTools: fakeLibrary(['feature_flag:read', 'query:read']),
        })
        expect(result.stdout).toBe(
            '{"group":"feature-flags","name":"Feature flags","tools":2,"usable":1}\n' +
                '{"group":"insights-analytics","name":"Insights & analytics","tools":1,"usable":0}\n'
        )
    })

    test.each([
        ['without credentials', {}, fakeLibrary([])],
        ['when the key lookup fails', { env: TEST_CREDENTIALS }, fakeLibrary([], { lookupFails: true })],
    ])('tools are browsable %s', async (_name, options, library) => {
        const result = await runHog(['api', 'tools', 'Feature flags'], { ...options, apiTools: library })
        expect(result.exitCode).toBe(0)
        expect(result.stdout).toBe(
            '{"group":"feature-flags","kind":"read","missingScopes":null,"name":"flag-list","summary":"Summary of flag-list","usable":null}\n' +
                '{"group":"feature-flags","kind":"destructive","missingScopes":null,"name":"flag-delete","summary":"Summary of flag-delete","usable":null}\n'
        )
    })

    test.each([
        ['an unknown group', ['api', 'tools', 'nope'], 'unknown_group', 1],
        ['an unknown tool', ['api', 'call', 'nope'], 'unknown_tool', 1],
        ['input that is not JSON', ['api', 'call', 'flag-list', '{limit'], 'invalid_json', 2],
        ['input that is not an object', ['api', 'call', 'flag-list', '[1]'], 'invalid_json', 2],
        ['input the schema rejects', ['api', 'call', 'flag-list', '{"limit":"x"}'], 'invalid_input', 2],
        ['a destructive tool without --confirm', ['api', 'call', 'flag-delete', '{"id":1}'], 'needs_confirmation', 1],
        ['an empty --project-id', ['api', 'call', 'flag-list', '{}', '--project-id', ''], 'invalid_input', 2],
        [
            'a --project-id that is not a number',
            ['api', 'call', 'flag-list', '{}', '--project-id', 'abc'],
            'invalid_input',
            2,
        ],
        [
            'an empty --organization-id',
            ['api', 'call', 'flag-list', '{}', '--organization-id', ' '],
            'invalid_input',
            2,
        ],
    ])('call refuses %s before calling PostHog', async (_name, argv, code, exitCode) => {
        const library = fakeLibrary(['*'])
        const result = await runHog(argv, { env: TEST_CREDENTIALS, apiTools: library })
        expect(result.exitCode).toBe(exitCode)
        expect(result.error().code).toBe(code)
        expect(library.calls).toEqual([])
    })

    test.each([
        [
            '--dry-run checks the input without calling',
            ['--dry-run'],
            { input: { limit: 2 }, tool: 'flag-list', valid: true },
            [],
        ],
        [
            'an organization override drops the saved project',
            ['--organization-id', '0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b'],
            { ok: 1 },
            [
                {
                    tool: 'flag-list',
                    input: { limit: 2 },
                    connection: {
                        apiKey: 'phx_test',
                        host: 'https://ph.example.com',
                        organizationId: '0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b',
                        clientName: 'hog',
                        clientVersion: expect.any(String),
                    },
                    confirm: false,
                },
            ],
        ],
        [
            'a call runs as hog in the chosen project',
            ['--project-id', '9'],
            { ok: 1 },
            [
                {
                    tool: 'flag-list',
                    input: { limit: 2 },
                    connection: {
                        apiKey: 'phx_test',
                        host: 'https://ph.example.com',
                        projectId: '9',
                        clientName: 'hog',
                        clientVersion: expect.any(String),
                    },
                    confirm: false,
                },
            ],
        ],
    ])('call: %s', async (_name, flags, output, calls) => {
        const library = fakeLibrary(['*'])
        const result = await runHog(['api', 'call', 'flag-list', '{"limit":2}', ...flags], {
            env: TEST_CREDENTIALS,
            apiTools: library,
        })
        expect(result.exitCode).toBe(0)
        expect(result.json()).toEqual(output)
        expect(library.calls).toEqual(calls)
    })

    test.each([
        ['names every scope the key is missing', false, 'insight:write, query:read'],
        ['keeps the scope PostHog named when the key lookup fails', true, 'insight:write'],
    ])('a refused call %s', async (_name, lookupFails, scopes) => {
        const library = fakeLibrary(['feature_flag:read'], {
            lookupFails,
            callResult: {
                ok: false,
                error: { code: 'permission_denied', message: 'denied', status: 403, missingScope: 'insight:write' },
            },
        })
        const result = await runHog(['api', 'call', 'insight-create', '{}'], {
            env: TEST_CREDENTIALS,
            apiTools: library,
        })
        expect(result.error()).toMatchObject({
            code: 'missing_scopes',
            message: `Your credentials need ${scopes} to call insight-create.`,
            hint: expect.stringContaining('personal API key'),
        })
    })

    test.each([
        ['PostHog refuses a field', { code: 'validation_error', message: 'Unknown field: rollout', status: 400 }, true],
        ['the endpoint is missing', { code: 'api_error', message: 'Not found', status: 404 }, true],
        ['PostHog fails for another reason', { code: 'api_error', message: 'Server error', status: 500 }, false],
    ] as const)(
        'a failed call when %s says whether the tool definitions may be out of date',
        async (_name, error, stale) => {
            const library = fakeLibrary(['*'], { callResult: { ok: false, error } })
            const result = await runHog(['api', 'call', 'flag-list', '{}'], {
                env: TEST_CREDENTIALS,
                apiTools: library,
            })

            expect(result.exitCode).toBe(1)
            const hint = result.error().hint ?? ''
            expect(hint.includes('Update hog to the latest version, or run `hog api refresh`')).toBe(stale)
        }
    )

    test.each([
        ['a tool it has never heard of', [], 'unknown_tool', 'If the tool is new, update hog to the latest version'],
        [
            'a new tool from the catalog this hog cannot run',
            [{ name: 'flag-forecast', reason: 'needs hook:flags/forecastHooks', builtIn: false }],
            'tool_unavailable',
            'Update hog to the latest version to use it.',
        ],
    ])('a call to %s says how to get it', async (_name, dropped, code, hint) => {
        const library = {
            ...fakeLibrary(['*']),
            catalog: () => ({ source: 'downloaded' as const, build: 'abc', tools: 3, dropped, rejected: null }),
        }
        const result = await runHog(['api', 'call', 'flag-forecast', '{}'], {
            env: TEST_CREDENTIALS,
            apiTools: library,
        })

        expect(result.exitCode).toBe(1)
        expect(result.error()).toMatchObject({ code, hint: expect.stringContaining(hint) })
    })

    test.each([
        ['an unlimited key reaches the project', [], 200, undefined, true],
        ["a key limited to the project's organization reaches it", ['org-a'], 200, 'org-a', true],
        [
            'a key limited to another organization does not',
            ['0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b'],
            200,
            'org-a',
            false,
        ],
        ["a key without project:read can't tell", ['org-a'], 403, undefined, null],
    ])('access: %s', async (_name, scopedOrganizations, status, projectOrganization, projectAllowed) => {
        const result = await runHog(['api', 'access'], {
            env: TEST_CREDENTIALS,
            apiTools: fakeLibrary(['feature_flag:read', 'feature_flag:write'], { scopedOrganizations }),
            respond: () => ({ status, body: status === 200 ? { id: 7, organization: projectOrganization } : {} }),
        })

        expect(result.json()).toMatchObject({
            usable: 2,
            tools: 3,
            projectAllowed,
            missingScopes: [
                { scope: 'insight:write', tools: 1, groups: ['insights-analytics'] },
                { scope: 'query:read', tools: 1, groups: ['insights-analytics'] },
            ],
        })
    })

    test('access answers for an OAuth login from its scopes, because the key lookup refuses OAuth tokens', async () => {
        const EU = 'https://eu.posthog.com'
        const record = {
            store: 'keychain',
            type: 'oauth',
            projectId: '42',
            host: EU,
            expiresAt: Date.UTC(2026, 0, 8),
            scopes: ['feature_flag:read', 'feature_flag:write'],
            loginId: 'login-1',
        }
        const result = await runHog(['api', 'access'], {
            env: { CLAUDECODE: '1' },
            files: { '/home/test/.config/hog/settings.json': JSON.stringify({ logins: { [EU]: record }, host: EU }) },
            keychain: { [EU]: JSON.stringify({ accessToken: 'pha_token', refreshToken: 'phr_token' }) },
            apiTools: fakeLibrary([], { lookupFails: true }),
        })

        expect(result.json()).toMatchObject({ usable: 2, tools: 3, projectAllowed: true })
    })

    test.each([
        [
            'stops before calling, naming every scope the login lacks',
            ['feature_flag:read'],
            'insight:write',
            {
                code: 'step_up_required',
                scopes: ['insight:write', 'query:read'],
                command: 'hog auth add --host https://eu.posthog.com insight:write query:read',
            },
            0,
        ],
        [
            'never puts a scope from the refusal text into a command',
            ['insight:write', 'query:read'],
            'insight:write $(curl example.com)',
            { code: 'missing_scopes' },
            1,
        ],
    ])('a call from an OAuth login %s', async (_name, held, missingScope, expected, calls) => {
        const EU = 'https://eu.posthog.com'
        const record = {
            store: 'keychain',
            type: 'oauth',
            projectId: '42',
            host: EU,
            expiresAt: Date.UTC(2026, 0, 8),
            scopes: held,
            loginId: 'login-1',
        }
        const library = fakeLibrary([], {
            lookupFails: true,
            callResult: {
                ok: false,
                error: { code: 'permission_denied', message: 'denied', status: 403, missingScope },
            },
        })
        const result = await runHog(['api', 'call', 'insight-create', '{}'], {
            env: { CLAUDECODE: '1' },
            files: { '/home/test/.config/hog/settings.json': JSON.stringify({ logins: { [EU]: record }, host: EU }) },
            keychain: { [EU]: JSON.stringify({ accessToken: 'pha_token', refreshToken: 'phr_token' }) },
            apiTools: library,
        })

        expect(result.error()).toMatchObject(expected)
        expect(String(result.error().command ?? '')).not.toContain('$(')
        expect(library.calls).toHaveLength(calls)
    })
})

const CACHE = '/home/test/.config/hog/api-catalog.json'
const NOW = Date.UTC(2026, 0, 1)
const HOUR = 60 * 60 * 1000

function catalog(names: string[], extra: Record<string, unknown> = {}): Record<string, unknown> {
    return {
        schemaVersion: 1,
        minHogVersion: '0.0.0',
        build: 'abc123',
        tools: names.map((name) => ({ name })),
        ...extra,
    }
}

const US = 'https://us.posthog.com'
const CATALOG_URL = `${US}/api/cli/catalog.json`

function cached(names: string[], ageMs: number, extra: Record<string, unknown> = {}): Record<string, string> {
    const entry = {
        fetchedAt: NOW - ageMs,
        etag: '"v1"',
        catalog: catalog(names, extra),
        retryAfter: null,
        failure: null,
    }
    return { [CACHE]: JSON.stringify({ hosts: { [US]: entry } }) }
}

function catalogLibrary(dropped: ApiCatalogDroppedTool[] = []): {
    build: (options: ApiToolLibraryOptions) => ApiToolLibrary
    received: () => unknown
} {
    let received: unknown
    return {
        received: () => received,
        build: (options) => {
            received = options.catalog
            const tools = (options.catalog as { tools?: unknown[]; build?: string } | undefined)?.tools
            return {
                ...fakeLibrary([]),
                catalog: () =>
                    tools
                        ? {
                              source: 'downloaded',
                              build: (options.catalog as { build: string }).build,
                              tools: tools.length - dropped.length,
                              dropped,
                              rejected: null,
                          }
                        : { source: 'bundled', build: null, tools: 0, dropped: [], rejected: null },
            }
        },
    }
}

const catalogRequests = (result: HogRun, url = CATALOG_URL): number =>
    result.requests.filter((r) => r.url === url).length

describe('hog api tool catalog', () => {
    test('downloads the catalog once a day and runs the tools it describes', async () => {
        const library = catalogLibrary()
        const first = await runHog(['api', 'groups'], {
            env: { CLAUDECODE: '1' },
            apiTools: library.build,
            respond: (url) =>
                url === CATALOG_URL ? { status: 200, body: catalog(['flag-list']) } : { status: 500, body: {} },
        })

        expect(first.exitCode).toBe(0)
        expect(catalogRequests(first)).toBe(1)
        expect(library.received()).toMatchObject({ build: 'abc123', tools: [{ name: 'flag-list' }] })

        const again = await runHog(['api', 'groups'], {
            env: { CLAUDECODE: '1' },
            apiTools: library.build,
            files: first.files,
        })

        expect(catalogRequests(again)).toBe(0)
        expect(library.received()).toMatchObject({ build: 'abc123' })
    })

    test('downloads again once the saved catalog is a day old', async () => {
        const library = catalogLibrary()
        const result = await runHog(['api', 'groups'], {
            env: { CLAUDECODE: '1' },
            apiTools: library.build,
            files: cached(['flag-list'], 25 * HOUR),
            respond: (url) =>
                url === CATALOG_URL
                    ? { status: 200, body: catalog(['flag-list', 'flag-new'], { build: 'def456' }) }
                    : { status: 500, body: {} },
        })

        expect(catalogRequests(result)).toBe(1)
        expect(library.received()).toMatchObject({ build: 'def456' })
    })

    test('revalidates a day-old catalog with its ETag, and keeps it on a 304', async () => {
        const library = catalogLibrary()
        const files = cached(['flag-list'], 25 * HOUR)
        const sent: (string | null)[] = []
        const revalidated = await runHog(['api', 'groups'], {
            env: { CLAUDECODE: '1' },
            apiTools: library.build,
            files,
            respond: (url, _body, _authorization, headers) => {
                if (url === CATALOG_URL) {
                    sent.push(headers.get('If-None-Match'))
                    return { status: 304, body: null }
                }
                return { status: 500, body: {} }
            },
        })
        const again = await runHog(['api', 'groups'], {
            env: { CLAUDECODE: '1' },
            apiTools: library.build,
            files: revalidated.files,
            now: NOW + HOUR,
        })

        expect(sent).toEqual(['"v1"'])
        expect(library.received()).toMatchObject({ build: 'abc123', tools: [{ name: 'flag-list' }] })
        expect(JSON.parse(revalidated.files[CACHE] ?? '{}').hosts[US]).toEqual({
            ...JSON.parse(files[CACHE]!).hosts[US],
            fetchedAt: NOW,
        })
        expect(catalogRequests(again)).toBe(0)
    })

    test.each([
        ['keeps the saved catalog when the download fails', cached(['flag-list'], 25 * HOUR), { build: 'abc123' }],
        ['runs the built-in tools when there is no saved catalog either', {}, undefined],
    ])('%s', async (_name, files, expected) => {
        const library = catalogLibrary()
        const result = await runHog(['api', 'groups'], {
            env: { CLAUDECODE: '1' },
            apiTools: library.build,
            files,
            respond: () => ({ status: 503, body: {} }),
        })

        expect(result.exitCode).toBe(0)
        expect(library.received()).toEqual(expected === undefined ? undefined : expect.objectContaining(expected))
    })

    test('waits an hour after a failed download before it tries again, and --debug says so', async () => {
        const library = catalogLibrary()
        const failed = await runHog(['api', 'groups'], {
            env: { CLAUDECODE: '1' },
            apiTools: library.build,
            respond: () => ({ status: 503, body: {} }),
        })
        const waiting = await runHog(['api', 'groups', '--debug'], {
            env: { CLAUDECODE: '1' },
            apiTools: library.build,
            files: failed.files,
            now: NOW + 30 * 60 * 1000,
            respond: () => ({ status: 200, body: catalog(['flag-list']) }),
        })
        const retried = await runHog(['api', 'groups'], {
            env: { CLAUDECODE: '1' },
            apiTools: library.build,
            files: failed.files,
            now: NOW + 61 * 60 * 1000,
            respond: () => ({ status: 200, body: catalog(['flag-list']) }),
        })

        expect(catalogRequests(failed)).toBe(1)
        expect(catalogRequests(waiting)).toBe(0)
        expect(waiting.stderr).toContain(
            '[debug] api catalog: the tools built into hog, because https://us.posthog.com answered 503'
        )
        expect(waiting.stderr).toContain(
            '[debug] api catalog: skipped the download until 2026-01-01T01:00:00.000Z, because the last one failed'
        )
        expect(catalogRequests(retried)).toBe(1)
        expect(library.received()).toMatchObject({ tools: [{ name: 'flag-list' }] })
    })

    const DOTENV = {
        '/work/p.env': 'HOG_PERSONAL_API_KEY=phx_test\nHOG_PROJECT_ID=7\nHOG_HOST=https://eu.posthog.com\n',
    }

    test.each([
        ['an EU host', [], { HOG_HOST: 'https://eu.posthog.com' }, {}, 'https://eu.posthog.com/api/cli/catalog.json'],
        [
            'a Cloud ingestion host',
            [],
            { HOG_HOST: 'https://eu.i.posthog.com' },
            {},
            'https://eu.posthog.com/api/cli/catalog.json',
        ],
        [
            'a self-hosted host',
            [],
            { HOG_HOST: 'https://ph.example.com/posthog' },
            {},
            'https://ph.example.com/posthog/api/cli/catalog.json',
        ],
        ['a key in the environment', [], TEST_CREDENTIALS, {}, 'https://ph.example.com/api/cli/catalog.json'],
        [
            'a key in --dotenv-file',
            ['--dotenv-file', '/work/p.env'],
            {},
            DOTENV,
            'https://eu.posthog.com/api/cli/catalog.json',
        ],
    ])('downloads the catalog from the app of %s', async (_name, flags, env, files, url) => {
        const library = catalogLibrary()
        const result = await runHog([...flags, 'api', 'groups'], {
            env: { CLAUDECODE: '1', ...env },
            files,
            apiTools: library.build,
            respond: (requested) =>
                requested === url ? { status: 200, body: catalog(['flag-list']) } : { status: 500, body: {} },
        })

        expect(catalogRequests(result, url)).toBe(1)
        expect(library.received()).toMatchObject({ tools: [{ name: 'flag-list' }] })
    })

    test('a host that serves no catalog runs the built-in tools, and --debug says why', async () => {
        const library = catalogLibrary()
        const result = await runHog(['api', 'groups', '--debug'], {
            env: { CLAUDECODE: '1', HOG_HOST: 'https://ph.example.com' },
            apiTools: library.build,
            respond: () => ({ status: 404, body: { detail: 'Not found' } }),
        })

        expect(result.exitCode).toBe(0)
        expect(library.received()).toBeUndefined()
        expect(result.stderr).toContain(
            "[debug] api catalog: the tools built into hog, because https://ph.example.com doesn't serve a tool catalog"
        )
    })

    test.each([
        [
            'a catalog that needs a newer hog',
            { HOG_DEBUG: '1' },
            catalog(['flag-list'], { minHogVersion: '99.0.0' }),
            1,
        ],
        ['HOG_API_CATALOG=bundled', { HOG_API_CATALOG: 'bundled' }, catalog(['flag-list']), 0],
    ])('runs the built-in tools for %s', async (_name, env, served, downloads) => {
        const library = catalogLibrary()
        const result = await runHog(['api', 'groups'], {
            env: { CLAUDECODE: '1', ...env },
            apiTools: library.build,
            respond: (url) => (url === CATALOG_URL ? { status: 200, body: served } : { status: 500, body: {} }),
        })

        expect(result.exitCode).toBe(0)
        expect(catalogRequests(result)).toBe(downloads)
        expect(library.received()).toBeUndefined()
    })

    test('with TLS verification off, neither downloads a catalog nor uses the saved one', async () => {
        const library = catalogLibrary()
        const result = await runHog(['api', 'groups', '--debug'], {
            env: { CLAUDECODE: '1', HOG_SKIP_SSL_VERIFICATION: '1' },
            apiTools: library.build,
            files: cached(['flag-list'], HOUR),
            respond: () => ({ status: 200, body: catalog(['flag-new']) }),
        })

        expect(catalogRequests(result)).toBe(0)
        expect(library.received()).toBeUndefined()
        expect(result.stderr).toContain(
            '[debug] api catalog: the tools built into hog, because TLS verification is off'
        )
    })

    test('--debug names the source and each tool hog kept built in', async () => {
        const library = catalogLibrary([{ name: 'flag-new', reason: 'unknown field response.redact', builtIn: true }])
        const result = await runHog(['api', 'groups', '--debug'], {
            env: { CLAUDECODE: '1' },
            apiTools: library.build,
            files: cached(['flag-list', 'flag-new'], HOUR),
        })

        expect(result.stderr).toContain('[debug] api catalog: 1 tools from the saved catalog')
        expect(result.stderr).toContain(
            '[debug] api catalog: kept the built-in flag-new, because unknown field response.redact'
        )
    })

    test('a catalog that needs a newer hog is ignored whole, and --debug says why', async () => {
        const library = catalogLibrary()
        const result = await runHog(['api', 'groups', '--debug'], {
            env: { CLAUDECODE: '1' },
            apiTools: library.build,
            files: cached(['flag-list'], HOUR, { minHogVersion: '99.0.0' }),
        })

        expect(library.received()).toBeUndefined()
        expect(result.stderr).toContain('the catalog needs hog 99.0.0 or later')
    })

    describe('refresh', () => {
        test('downloads now and reports what changed and what hog kept built in', async () => {
            const library = catalogLibrary([
                {
                    name: 'flag-renamed',
                    reason: "needs hook:flags/newHooks, which this hog doesn't have",
                    builtIn: false,
                },
            ])
            const result = await runHog(['api', 'refresh'], {
                env: { CLAUDECODE: '1' },
                apiTools: library.build,
                files: cached(['flag-list', 'flag-old'], HOUR),
                respond: (url) =>
                    url === CATALOG_URL
                        ? { status: 200, body: catalog(['flag-list', 'flag-new', 'flag-renamed'], { build: 'def456' }) }
                        : { status: 500, body: {} },
            })

            expect(result.exitCode).toBe(0)
            expect(catalogRequests(result)).toBe(1)
            expect(result.json()).toEqual({
                status: 'updated',
                tools: 2,
                build: 'def456',
                fetchedAt: '2026-01-01T00:00:00.000Z',
                added: ['flag-new'],
                removed: ['flag-old'],
                dropped: [
                    {
                        name: 'flag-renamed',
                        reason: "needs hook:flags/newHooks, which this hog doesn't have",
                        builtIn: false,
                    },
                ],
            })
        })

        test('says the catalog is up to date when nothing changed', async () => {
            const result = await runHog(['api', 'refresh'], {
                stdoutIsTTY: true,
                apiTools: catalogLibrary().build,
                files: cached(['flag-list'], HOUR),
                respond: (url) =>
                    url === CATALOG_URL ? { status: 200, body: catalog(['flag-list']) } : { status: 500, body: {} },
            })

            expect(result.exitCode).toBe(0)
            expect(result.stdout).toContain('The API tool catalog is up to date')
        })

        test.each([
            ['offline', {}, () => ({ status: 503, body: {} }), 'catalog_unreachable'],
            [
                'pinned to the built-in tools',
                { HOG_API_CATALOG: 'bundled' },
                () => ({ status: 200, body: catalog(['x']) }),
                'catalog_not_used',
            ],
        ])('fails when %s, and keeps the catalog hog has', async (_name, env, respond, code) => {
            const files = cached(['flag-list'], HOUR)
            const result = await runHog(['api', 'refresh'], {
                env: { CLAUDECODE: '1', ...env },
                apiTools: catalogLibrary().build,
                files,
                respond,
            })

            expect(result.exitCode).toBe(1)
            expect(result.error().code).toBe(code)
            expect(JSON.parse(result.files[CACHE] ?? '{}').hosts[US].catalog).toEqual(catalog(['flag-list']))
        })
    })
})
