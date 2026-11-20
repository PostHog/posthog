import assert from 'node:assert/strict'
import { test } from 'node:test'

import { createApiToolLibrary } from '@posthog/mcp/dist/cli-library.mjs'
import { createPostHogClient } from '@posthog/sdk'

const host = 'https://api.example.com'
const publicBaseUrl = 'https://app.example.com'
const projectId = 23
const token = 'phx_example'
const organizationId = 'example-org'

function fixture() {
    const calls = []
    const flag = { id: 17, key: 'sample', name: 'Sample flag', active: true, private_field: true }
    const fetch = async (url, init = {}) => {
        const path = new URL(url).pathname
        calls.push({ path, method: init.method ?? 'GET', headers: new Headers(init.headers), body: init.body })
        if (path.endsWith('/feature_flags/')) {
            return Response.json({ results: [flag], count: 1, next: null, previous: null })
        }
        if (path.endsWith('/access_control_default_rules/')) {
            return Response.json({ resource: 'dashboard', access_level: 'viewer' })
        }
        if (path.includes('/personal_api_keys/@current')) {
            return Response.json({
                scopes: ['*'],
                scoped_teams: [],
                scoped_organizations: [],
                user_distinct_id: 'example-user',
            })
        }
        if (path.match(/\/projects\/\d+\/?$/)) {
            return Response.json({
                id: Number(path.split('/').filter(Boolean).at(-1)),
                organization: organizationId,
                is_ai_data_processing_approved: false,
            })
        }
        if (path.endsWith('/users/@me/')) {
            return Response.json({ distinct_id: 'example-user', team: { id: projectId, organization: organizationId } })
        }
        if (path.endsWith('/organizations/example-org/')) {
            return Response.json({ id: organizationId, is_ai_data_processing_approved: false })
        }
        return Response.json({ detail: 'Unhandled fixture path ' + path }, { status: 404 })
    }
    return { fetch, calls }
}

const settings = { env: false, baseUrl: host, publicBaseUrl, projectId, organizationId, token }

test('SDK methods and hog return the same projection and handwritten lookup result', async () => {
    const sdkFixture = fixture()
    const cliFixture = fixture()
    const client = createPostHogClient({ ...settings, fetch: sdkFixture.fetch })
    const library = createApiToolLibrary({ fetch: cliFixture.fetch })
    const connection = {
        apiKey: token,
        host,
        publicBaseUrl,
        projectId: String(projectId),
        organizationId,
        clientName: 'hog',
        clientVersion: 'test',
    }
    for (const [name, method, input] of [
        ['feature-flag-get-all', client.featureFlags.list, { limit: 2 }],
        ['feature-flag-get-definition-by-key', client.flags.featureFlagGetDefinitionByKey, { key: 'sample' }],
    ]) {
        const actual = await method(input)
        const cli = await library.call(name, input, connection, false)
        assert.equal(cli.ok, true, JSON.stringify(cli))
        assert.deepEqual(actual, cli.value)
        if (name === 'feature-flag-get-all') {
            assert.equal(actual.results[0]._posthogUrl, publicBaseUrl + '/project/23/feature-flags/17')
            assert.equal(actual.results[0].private_field, undefined)
        }
    }
    const requests = (calls) =>
        calls
            .filter((call) => call.path.endsWith('/feature_flags/'))
            .map(({ method, path, body }) => ({ method, path, body }))
    assert.deepEqual(requests(sdkFixture.calls), requests(cliFixture.calls))
})

test('a Tasks proxy supplies the credential, preserves the route prefix and pins the project', async () => {
    const { fetch, calls } = fixture()
    const client = createPostHogClient({
        env: false,
        authMode: 'proxy',
        baseUrl: host + '/proxy',
        publicBaseUrl,
        projectId,
        taskId: 'example-task',
        fetch,
    })
    const output = await client.project(42).featureFlags.list({})
    assert.equal(output.results[0]._posthogUrl, publicBaseUrl + '/project/42/feature-flags/17')
    assert.ok(calls.some(({ path }) => path === '/proxy/api/projects/42/feature_flags/'))
    for (const { headers, path } of calls) {
        assert.ok(path.startsWith('/proxy/'))
        assert.equal(headers.has('authorization'), false)
        assert.equal(headers.get('x-posthog-task-id'), 'example-task')
    }
})

test('scoped clients for one project share the project and credential lookups', async () => {
    const { fetch, calls } = fixture()
    const client = createPostHogClient({ ...settings, fetch })
    await client.project(42).featureFlags.list({})
    const afterFirst = calls.length
    await client.project(42).featureFlags.list({})
    assert.deepEqual(
        calls.slice(afterFirst).map(({ path }) => path),
        ['/api/projects/42/feature_flags/']
    )
})

test('signed writes bind confirmation to the client and project and consume it once', async () => {
    const { fetch, calls } = fixture()
    const client = createPostHogClient({ ...settings, fetch })
    const prepared = await client.accessControl.accessControlDefaultRuleSetPrepare({
        resource: 'dashboard',
        access_level: 'viewer',
    })
    const input = { confirmation_hash: prepared.confirmation_hash, confirmation: 'confirm' }
    const run = (caller, options) => caller.accessControl.accessControlDefaultRuleSetExecute(input, options)
    const other = createPostHogClient({ ...settings, fetch })
    await assert.rejects(run(other, { confirm: true }))
    await assert.rejects(run(client.project(31), { confirm: true }))
    assert.equal(calls.filter(({ method }) => method === 'PUT').length, 0)
    const results = await Promise.allSettled([run(client, { confirm: true }), run(client, { confirm: true })])
    assert.equal(results.filter(({ status }) => status === 'fulfilled').length, 1, JSON.stringify(results))
    assert.equal(calls.filter(({ method }) => method === 'PUT').length, 1)
})

test('cancellation during a read prevents the pending mutation', async () => {
    const controller = new AbortController()
    const writes = []
    const client = createPostHogClient({
        ...settings,
        fetch: async (url, init) => {
            if (init.method !== 'GET' && init.method) {
                writes.push(init.method)
            }
            controller.abort()
            return Response.json({ is_ai_data_processing_approved: false })
        },
    })
    await assert.rejects(
        client.featureFlags.archive({ id: 17 }, { confirm: true, signal: controller.signal }),
        (error) => error.details.kind === 'aborted'
    )
    await new Promise((resolve) => setImmediate(resolve))
    assert.deepEqual(writes, [])
})

test('the SDK exposes shared validation, authorization and consent errors', async () => {
    const { fetch, calls } = fixture()
    const client = createPostHogClient({
        ...settings,
        fetch: (url, options) =>
            String(url).includes('/feature_flags/')
                ? Response.json(
                      { type: 'authentication_error', code: 'permission_denied', detail: 'Denied' },
                      { status: 403 }
                  )
                : fetch(url, options),
    })
    await assert.rejects(client.featureFlags.list({ limit: 'invalid' }), (err) => err.details.code === 'invalid_input')
    await assert.rejects(
        client.featureFlags.list({}),
        (err) => err.details.code === 'permission_denied' && err.details.status === 403
    )
    await assert.rejects(
        client.mcpAnalytics.mcpAnalyticsSessionsGenerateIntent({ id: '00000000-0000-4000-8000-000000000001' }),
        (err) => err.details.code === 'ai_consent_required'
    )
    assert.ok(calls.every(({ method }) => method === 'GET'))
})

test('switch-project updates its client while a pinned client keeps its original project', async () => {
    const { fetch, calls } = fixture()
    const client = createPostHogClient({ ...settings, fetch })
    const pinned = client.project(projectId)
    await client.workspace.switchProject({ projectId: 31 })
    assert.equal((await client.context()).projectId, 31)
    await client.featureFlags.list({})
    assert.ok(calls.some(({ path }) => path === '/api/projects/31/feature_flags/'))
    await assert.rejects(pinned.workspace.switchProject({ projectId: 31 }))
    await pinned.featureFlags.list({})
    assert.ok(calls.some(({ path }) => path === '/api/projects/23/feature_flags/'))
})
