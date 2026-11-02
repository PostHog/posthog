import { describe, expect, test } from 'bun:test'

import type { ApiConnection, ApiToolLibrary, ApiToolResult, ApiToolSummary } from '@posthog/mcp/src/cli/library-types'

import { runHog, TEST_CREDENTIALS } from '@/testing'

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
            ['--organization-id', 'org-b'],
            { ok: 1 },
            [
                {
                    tool: 'flag-list',
                    input: { limit: 2 },
                    connection: {
                        apiKey: 'phx_test',
                        host: 'https://ph.example.com',
                        organizationId: 'org-b',
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
            message: `The personal API key needs ${scopes} to call insight-create.`,
        })
    })

    test.each([
        ['an unlimited key reaches the project', [], 200, undefined, true],
        ["a key limited to the project's organization reaches it", ['org-a'], 200, 'org-a', true],
        ['a key limited to another organization does not', ['org-b'], 200, 'org-a', false],
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
})
