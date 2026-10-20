import assert from 'node:assert/strict'
import { test } from 'node:test'

import { PostHogError, createPostHogClient } from '../dist/index.js'

const flag = { id: 17, key: 'sample-flag', status: 'ARCHIVED', active: false, archived: true, filters: { groups: [] } }
const json = (body, status = 200, headers = {}) =>
    new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json', ...headers } })
const makeClient = (fetch, options = {}) =>
    createPostHogClient({ env: false, token: 'phx_example', projectId: 23, fetch, ...options })
const errorKind = (kind) => (error) => error instanceof PostHogError && error.details.kind === kind

test('typed operations bind requests, project responses, and use the public URL', async () => {
    const calls = []
    const client = makeClient(
        async (url, init) => {
            calls.push({ url, init })
            return json(flag, 200, { 'x-request-id': 'example-request' })
        },
        { baseUrl: 'https://api.example.com/prefix/', publicBaseUrl: 'https://app.example.com' }
    )
    const input = { id: 17 }
    const result = await client.featureFlags.archive(input)
    assert.deepEqual(input, { id: 17 })
    assert.equal(calls[0].url, 'https://api.example.com/prefix/api/projects/23/feature_flags/17/archive/')
    assert.equal(calls[0].init.method, 'POST')
    assert.equal(calls[0].init.body, undefined)
    assert.equal(calls[0].init.headers.get('authorization'), 'Bearer phx_example')
    assert.equal(calls[0].init.redirect, 'error')
    assert.deepEqual(result, {
        data: {
            id: 17,
            key: 'sample-flag',
            status: 'ARCHIVED',
            active: false,
            archived: true,
            _posthogUrl: 'https://app.example.com/project/23/feature_flags/17',
        },
        meta: { status: 200, requestId: 'example-request' },
    })
})

test('proxy mode omits credentials, preserves its route prefix, and requires a project', async () => {
    const calls = []
    const client = createPostHogClient({
        env: false,
        authMode: 'proxy',
        baseUrl: 'https://proxy.example.com/task/posthog',
        publicBaseUrl: 'https://eu.posthog.com',
        projectId: 23,
        fetch: async (url, init) => {
            calls.push({ url, init })
            return json(flag)
        },
    })
    const result = await client.project(24).featureFlags.archive({ id: 17 })
    assert.equal(calls[0].url, 'https://proxy.example.com/task/posthog/api/projects/24/feature_flags/17/archive/')
    assert.equal(calls[0].init.headers.has('authorization'), false)
    assert.equal(result.data._posthogUrl, 'https://eu.posthog.com/project/24/feature_flags/17')
    assert.deepEqual(await client.context(), { projectId: 23, source: 'explicit' })
    const missing = createPostHogClient({
        env: false,
        authMode: 'proxy',
        baseUrl: 'https://proxy.example.com',
        publicBaseUrl: 'https://us.posthog.com',
        fetch: () => assert.fail('must resolve project before calling API'),
    })
    await assert.rejects(missing.featureFlags.archive({ id: 17 }), errorKind('project_resolution'))
})

test('configuration is lazy and explicit settings override environment defaults', async (t) => {
    t.mock.property(process, 'env', {
        POSTHOG_PERSONAL_API_KEY: 'phx_environment',
        POSTHOG_API_URL: 'https://env.example.com',
        POSTHOG_PROJECT_ID: '10',
    })
    const client = createPostHogClient({
        fetch: async (url, init) => {
            assert.equal(url, 'https://env.example.com/api/projects/11/feature_flags/17/archive/')
            assert.equal(init.headers.get('authorization'), 'Bearer phx_environment')
            return json(flag)
        },
    })
    process.env.POSTHOG_PROJECT_ID = '11'
    const firstCall = client.featureFlags.archive({ id: 17 })
    process.env.POSTHOG_PROJECT_ID = '12'
    await firstCall
    assert.equal((await client.context()).projectId, 11)
    assert.deepEqual(await createPostHogClient({ token: 'phx_explicit', projectId: 13 }).context(), {
        projectId: 13,
        source: 'explicit',
    })
    process.env.POSTHOG_AUTH_MODE = 'proxy'
    process.env.POSTHOG_PUBLIC_URL = 'https://us.posthog.com'
    const proxy = createPostHogClient({
        fetch: async (_url, init) => {
            assert.equal(init.headers.has('authorization'), false)
            return json(flag)
        },
    })
    await proxy.featureFlags.archive({ id: 17 })
    process.env.POSTHOG_PROJECT_ID = 'invalid-default'
    const scoped = createPostHogClient()
    assert.deepEqual(await scoped.project(15).context(), { projectId: 15, source: 'explicit' })
    await assert.rejects(scoped.context(), errorKind('configuration'))
})

test('project resolution respects credential scope and never selects the first permitted project', async (t) => {
    const cases = [
        { name: 'one scoped project', token: { scoped_teams: [7] }, expected: { projectId: 7, source: 'token_scope' } },
        {
            name: 'selected permitted project',
            token: { scoped_teams: [7, 8] },
            user: { team: { id: 8, organization: 'example-org' } },
            expected: { projectId: 8, organizationId: 'example-org', source: 'user_selection' },
        },
        {
            name: 'organization scope',
            token: { scoped_teams: null, scoped_organizations: ['example-org'] },
            user: { team: { id: 8, organization: 'example-org' } },
            expected: { projectId: 8, organizationId: 'example-org', source: 'user_selection' },
        },
        {
            name: 'selected project outside scope',
            token: { scoped_teams: [7, 8] },
            user: { team: { id: 9 } },
            failure: 'ambiguous',
        },
        {
            name: 'selected project outside organization',
            token: { scoped_organizations: ['allowed-org'] },
            user: { team: { id: 9, organization: 'other-org' } },
            failure: 'missing',
        },
        {
            name: 'missing user read scope',
            token: { scoped_teams: [7, 8] },
            user: {},
            status: 403,
            failure: 'discovery_unavailable',
        },
        {
            name: 'OAuth project scope',
            token: { active: true, scoped_teams: [7] },
            oauth: true,
            expected: { projectId: 7, source: 'token_scope' },
        },
    ]
    for (const entry of cases) {
        await t.test(entry.name, async () => {
            const requests = []
            const client = makeClient(
                async (url, init) => {
                    requests.push(url)
                    if (url.endsWith('/api/users/@me/')) {
                        return json(entry.user, entry.status)
                    }
                    assert.ok(url.endsWith(entry.oauth ? '/oauth/introspect' : '/api/personal_api_keys/@current'))
                    if (entry.oauth) {
                        assert.deepEqual(JSON.parse(init.body), { token: 'pha_example' })
                    }
                    return json(entry.token)
                },
                { projectId: undefined, token: entry.oauth ? 'pha_example' : 'phx_example' }
            )
            if (entry.failure) {
                await assert.rejects(
                    client.context(),
                    (error) => error.details.projectResolution.reason === entry.failure
                )
            } else {
                assert.deepEqual(await client.context(), entry.expected)
                await client.context()
            }
            assert.equal(requests.length, entry.user ? 2 : 1)
        })
    }
})

test('concurrent callers share discovery while one caller may cancel independently', async () => {
    const discovery = Promise.withResolvers()
    let lookups = 0
    const client = makeClient(
        async (url) => {
            if (url.endsWith('/api/personal_api_keys/@current')) {
                lookups++
                return discovery.promise
            }
            return json(flag)
        },
        { projectId: undefined }
    )
    const controller = new AbortController()
    const first = client.context({ signal: controller.signal })
    const second = client.context()
    controller.abort()
    await assert.rejects(first, errorKind('aborted'))
    discovery.resolve(json({ scoped_teams: [7] }))
    assert.equal((await second).projectId, 7)
    assert.equal(lookups, 1)
})

test('failed discovery can be retried and API failures never trigger project fallback or write retries', async () => {
    let calls = 0
    const client = makeClient(
        async () => (++calls === 1 ? json({ detail: 'unavailable' }, 503) : json({ scoped_teams: [7] })),
        { projectId: undefined }
    )
    await assert.rejects(client.context(), errorKind('api'))
    assert.equal((await client.context()).projectId, 7)
    for (const status of [400, 403, 404, 429]) {
        let writes = 0
        const denied = makeClient(async () => {
            writes++
            return json({ code: 'example_error', detail: 'Request rejected.', attr: 'id' }, status, {
                'retry-after': '2',
                'x-request-id': 'example',
            })
        })
        await assert.rejects(
            denied.featureFlags.archive({ id: 17 }),
            (error) =>
                error.details.status === status &&
                error.details.code === 'example_error' &&
                error.details.retryAfterMs === 2000 &&
                error.details.requestId === 'example' &&
                error.details.fields[0].path[0] === 'id'
        )
        assert.equal(writes, 1)
    }
})

test('input is validated while successful responses use TypeScript contracts without schema validation', async () => {
    const client = makeClient(() => assert.fail('invalid input reached the network'))
    for (const input of [{ id: '17' }, { id: 17, surprise: true }, { id: NaN }, { id: 17, value: () => 1 }]) {
        await assert.rejects(client.featureFlags.archive(input), errorKind('input_validation'))
    }
    for (const body of [{ id: 17 }, { ...flag, id: '17' }]) {
        for (const status of [200, 201]) {
            const result = await makeClient(async () => json(body, status)).featureFlags.archive({ id: 17 })
            assert.equal(result.data.id, body.id)
            assert.equal(result.meta.status, status)
        }
    }
    const dashboard = { id: 18, name: 'Sample dashboard' }
    const dashboards = await makeClient(async () => json({ results: [dashboard] })).dashboards.list({ limit: 1 })
    assert.deepEqual(dashboards.data.results, [
        { ...dashboard, _posthogUrl: 'https://us.posthog.com/project/23/dashboard/18' },
    ])
    await assert.rejects(
        makeClient(async () => new Response('invalid JSON')).featureFlags.archive({ id: 17 }),
        errorKind('response_validation')
    )
})

test('query parameters are URL encoded and PATCH omission does not apply serializer defaults', async () => {
    const client = makeClient(async (url, init) => {
        if (init.method === 'GET') {
            const params = new URL(url).searchParams
            assert.equal(params.get('search'), 'a & b')
            assert.equal(params.get('tags'), '["example"]')
            return json({ count: 0, results: [] })
        }
        assert.equal(init.method, 'PATCH')
        assert.deepEqual(JSON.parse(init.body), { name: 'Renamed dashboard', description: 'Example description' })
        return json({})
    })
    await client.featureFlags.list({ search: 'a & b', tags: '["example"]' })
    // The response is intentionally incomplete; request assertions still verify omission before validation fails.
    await assert.rejects(
        client.dashboards.update({ id: 3, name: 'Renamed dashboard', description: 'Example description' }),
        errorKind('response_validation')
    )
})

test('the deadline and cancellation apply even when a supplied fetch ignores AbortSignal', async (t) => {
    t.mock.timers.enable({ apis: ['setTimeout'] })
    const client = makeClient(() => new Promise(() => {}))
    const result = client.featureFlags.archive({ id: 17 }, { timeoutMs: 50 })
    t.mock.timers.tick(51)
    await assert.rejects(result, errorKind('timeout'))
    const controller = new AbortController()
    controller.abort()
    await assert.rejects(client.featureFlags.archive({ id: 17 }, { signal: controller.signal }), errorKind('aborted'))
})

test('analytics queries apply project defaults without mutating input and preserve structured results', async () => {
    const input = { series: [{ kind: 'EventsNode', event: 'example_event' }] }
    const calls = []
    const client = makeClient(async (url, init) => {
        calls.push(url)
        if (init.method === 'GET') {
            return json({ test_account_filters_default_checked: true })
        }
        const body = JSON.parse(init.body)
        assert.equal(body.query.kind, 'TrendsQuery')
        assert.equal(body.query.filterTestAccounts, true)
        assert.equal(body.query.series[0].event, 'example_event')
        return json({
            results: [{ label: 'example_event', data: [3, 5] }],
            error: null,
            query_status: null,
            timings: null,
            modifiers: { bounceRatePageViewMode: null },
            unexpected_additive_field: true,
        })
    })
    const output = await client.queries.trends(input)
    assert.equal(input.filterTestAccounts, undefined)
    assert.equal(output.data.state, 'complete')
    assert.deepEqual(output.data.result.results, [{ label: 'example_event', data: [3, 5] }])
    assert.equal(output.data.query.filterTestAccounts, true)
    assert.equal(calls.length, 2)
})

test('queries expose pending and failed states, and explicit filtering avoids a project-settings lookup', async () => {
    const status = {
        id: 'example-query',
        query_async: true,
        team_id: 23,
        error: false,
        complete: false,
        error_message: null,
        error_code: null,
        labels: null,
        start_time: null,
        query_progress: null,
    }
    for (const [response, state] of [
        [{ query_status: status }, 'pending'],
        [{ query_status: { ...status, complete: true, error: true, error_message: 'Example failure' } }, 'failed'],
    ]) {
        const client = makeClient(async (_url, init) => {
            assert.equal(init.method, 'POST')
            const body = JSON.parse(init.body)
            assert.equal(body.refresh, 'async')
            assert.equal(body.query.filterTestAccounts, false)
            assert.equal(body.query.refresh, undefined)
            return json(response, 202)
        })
        const output = await client.queries.trends({
            series: [{ kind: 'EventsNode', event: 'example_event' }],
            filterTestAccounts: false,
            refresh: 'async',
        })
        assert.equal(output.data.state, state)
        assert.equal(output.data.queryStatus.id, 'example-query')
    }
    let calls = 0
    const denied = makeClient(async () => {
        calls++
        return json({}, 403)
    })
    await assert.rejects(
        denied.queries.trends({ series: [] }),
        (error) => error.details.kind === 'input_validation' && error.details.message.includes('filterTestAccounts')
    )
    assert.equal(calls, 1)
})

test('SQL sends structured HogQL input and returns query-dependent cells without an asserted row shape', async () => {
    const client = makeClient(async (_url, init) => {
        assert.deepEqual(JSON.parse(init.body), {
            query: { kind: 'HogQLQuery', query: 'SELECT {value}', values: { value: 5 } },
        })
        return json({
            columns: ['example'],
            types: [['example', 'Int64']],
            results: [[5], [null], [{ nested: true }]],
            error: null,
            query_status: null,
            hasMore: null,
        })
    })
    const result = await client.queries.sql({ query: 'SELECT {value}', values: { value: 5 } })
    assert.equal(result.data.state, 'complete')
    assert.deepEqual(result.data.result.results, [[5], [null], [{ nested: true }]])
})
