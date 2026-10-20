import assert from 'node:assert/strict'
import { test } from 'node:test'

import { operations } from '../dist/discovery.js'

const operation = (name) => operations.find((item) => item.toolName === name || item.method === name)
import { createPostHogClient, PostHogError } from '../dist/index.js'

function invoke(client, name, input = {}, options) {
    const tool = operation(name)
    assert.ok(tool, `Missing ${name}`)
    const [namespace, method] = tool.method.split('.')
    return client[namespace][method](input, options)
}

const makeClient = (fetch, options = {}) =>
    createPostHogClient({ env: false, token: 'phx_example', projectId: 23, fetch, ...options })

test('shared handlers retain soft deletes, custom validation, hooks, and proxy authentication', async () => {
    const calls = []
    const client = makeClient(
        async (url, init) => {
            calls.push({ url, init, body: init.body && JSON.parse(init.body) })
            return Response.json({
                id: 17,
                key: 'sample-flag',
                filters: { aggregation_group_type_index: 1, groups: [{ properties: [], rollout_percentage: 20 }] },
            })
        },
        {
            token: undefined,
            authMode: 'proxy',
            baseUrl: 'https://proxy.example.com/tasks/posthog',
            publicBaseUrl: 'https://eu.posthog.com',
        }
    )
    await invoke(client, 'delete-feature-flag', { id: '17' })
    assert.equal(calls[0].url, 'https://proxy.example.com/tasks/posthog/api/projects/23/feature_flags/17/')
    assert.equal(calls[0].init.method, 'PATCH')
    assert.deepEqual(calls[0].body, { deleted: true })
    await invoke(client, 'update-feature-flag', {
        id: 17,
        filters: { groups: [{ properties: [], rollout_percentage: 50 }] },
    })
    assert.equal(calls[1].init.method, 'GET')
    assert.equal(calls[2].init.method, 'PATCH')
    assert.equal(calls[2].body.filters.aggregation_group_type_index, 1)
    assert.ok(calls.every(({ init }) => !init.headers.has('authorization') && init.redirect === 'error'))
    await assert.rejects(
        invoke(client, 'notebooks-create-markdown', { title: '' }),
        (error) => error instanceof PostHogError && error.details.kind === 'input_validation'
    )
    assert.equal(calls.length, 3)
})

test('confirmed actions require the matching client, purpose, and single-use user confirmation', async () => {
    const calls = []
    const fetch = async (url, init) => {
        calls.push({ url, init })
        return Response.json({ resource: 'dashboard', resource_id: null, access_level: 'viewer' })
    }
    const client = makeClient(fetch, { organizationId: 'example-org' })
    const prepared = await invoke(client, 'access-control-default-rule-set-prepare', {
        resource: 'dashboard',
        access_level: 'viewer',
    })
    assert.equal(calls.length, 0)
    const args = { confirmation_hash: prepared.data.confirmation_hash, confirmation: 'confirm' }
    for (const [caller, parameters] of [
        [client, { ...args, confirmation: 'yes' }],
        [makeClient(fetch, { organizationId: 'example-org' }), args],
    ]) {
        await assert.rejects(
            invoke(caller, 'access-control-default-rule-set-execute', parameters),
            (error) => error.details.kind === 'tool'
        )
    }
    assert.equal(calls.length, 0)
    const results = await Promise.allSettled([
        invoke(client, 'access-control-default-rule-set-execute', args),
        invoke(client, 'access-control-default-rule-set-execute', args),
    ])
    assert.equal(results.filter(({ status }) => status === 'fulfilled').length, 1)
    assert.equal(calls.length, 1)
    assert.equal(calls[0].init.method, 'PUT')
    assert.match(calls[0].url, /\/api\/organizations\/example-org\/projects\/23\/access_control_default_rules\/$/)
    const other = await invoke(client, 'access-control-default-rule-set-prepare', {
        resource: 'dashboard',
        access_level: 'viewer',
    })
    await assert.rejects(
        invoke(client, 'access-control-member-rule-set-execute', {
            confirmation_hash: other.data.confirmation_hash,
            confirmation: 'confirm',
        }),
        /different action/
    )
    assert.equal(calls.length, 1)
})

test('handwritten tools use task context and produce their structured contracts', async () => {
    const calls = []
    const client = makeClient(
        async (url, init) => {
            calls.push({ url, init })
            return Response.json(url.endsWith('/notebooks/') ? { short_id: 'exampleNotebook' } : { results: [] }, {
                headers: { 'x-request-id': 'example-request' },
            })
        },
        { taskId: 'example-task' }
    )
    const notebook = await invoke(client, 'notebooks-create-markdown', {
        title: 'Sample report',
        markdown: 'Sample text.',
    })
    assert.deepEqual(notebook.data, {
        notebook_id: 'exampleNotebook',
        title: 'Sample report',
        _posthogUrl: 'https://us.posthog.com/project/23/notebooks/exampleNotebook',
    })
    assert.equal(notebook.meta.requestId, 'example-request')
    assert.equal(JSON.parse(calls[0].init.body).text_content, '# Sample report\n\nSample text.')
    await invoke(client, 'tasks-artifacts-list')
    assert.match(calls[1].url, /\/tasks\/example-task\/artifacts\/$/)
    assert.equal(calls[1].init.headers.get('X-PostHog-Task-Id'), 'example-task')
    const reference = await invoke(client, 'llma-parser-recipe-reference')
    assert.equal(typeof reference.data.reference, 'string')
    assert.ok(reference.data.reference.includes('recipe'))
    assert.equal(calls.length, 2)
})

test('embedded query wrappers and gated tools remain callable with their original request behavior', async () => {
    const calls = []
    const client = makeClient(async (url, init) => {
        calls.push({ url, init })
        return Response.json({ results: [], hasMore: false })
    })
    await invoke(client, 'tasks-list')
    assert.match(calls[0].url, /\/api\/projects\/23\/tasks\//)
    const query = operation('query-mcp-tool-stats')
    assert.ok(query.method.startsWith('mcpAnalytics.'))
    await invoke(client, 'query-mcp-tool-stats', { toolName: 'tasks-list' })
    const body = JSON.parse(calls.at(-1).init.body)
    assert.equal(body.query.kind, 'MCPToolStatsQuery')
})

test('MCP error responses and consent refusals become SDK errors without performing the protected action', async () => {
    const client = makeClient(async () =>
        Response.json({ detail: 'Not allowed.' }, { status: 403, headers: { 'x-request-id': 'permission-example' } })
    )
    await assert.rejects(
        invoke(client, 'tasks-list'),
        (error) =>
            error instanceof PostHogError &&
            error.details.kind === 'api' &&
            error.details.status === 403 &&
            error.details.requestId === 'permission-example'
    )
    const calls = []
    const consent = makeClient(
        async (url) => {
            calls.push(url)
            return Response.json({ organization: { id: 'example-org', is_ai_data_processing_approved: false } })
        },
        { organizationId: 'example-org' }
    )
    await assert.rejects(invoke(consent, 'mcp-analytics-intent-clusters-recompute'), /Approve AI data processing/)
    assert.equal(calls.length, 1)
    assert.match(calls[0], /\/api\/users\/@me\/$/)
})

test('context switches persist per client while explicitly scoped clients stay immutable', async () => {
    const calls = []
    const fetch = async (url) => {
        calls.push(url)
        const project = url.match(/\/api\/projects\/(23|24)\/$/)
        if (project) {
            return Response.json({ id: Number(project[1]), organization: `org-${project[1]}` })
        }
        if (url.includes('/api/organizations/')) {
            return Response.json({ id: 'org-24', name: 'Example org' })
        }
        return Response.json({ results: [] })
    }
    const client = makeClient(fetch)
    const scoped = client.project(23)
    const other = makeClient(fetch)
    await invoke(client, 'switch-project', { projectId: 24 })
    assert.deepEqual(await client.context(), { projectId: 24, organizationId: 'org-24', source: 'explicit' })
    await invoke(client, 'tasks-list')
    assert.match(calls.at(-1), /\/api\/projects\/24\/tasks\//)
    await invoke(other, 'tasks-list')
    assert.match(calls.at(-1), /\/api\/projects\/23\/tasks\//)
    await assert.rejects(invoke(scoped, 'switch-project', { projectId: 24 }), /immutable project scope/)
    await invoke(scoped, 'tasks-list')
    assert.match(calls.at(-1), /\/api\/projects\/23\/tasks\//)
})

test('canceling a shared read-before-write hook prevents the subsequent write', async () => {
    const controller = new AbortController()
    const calls = []
    const client = makeClient(async (url, init) => {
        calls.push({ url, init })
        controller.abort()
        return Response.json({ id: 17, filters: { aggregation_group_type_index: 1 } })
    })
    await assert.rejects(
        invoke(client, 'update-feature-flag', { id: 17, filters: { groups: [] } }, { signal: controller.signal }),
        (error) => error instanceof PostHogError && error.details.kind === 'aborted'
    )
    assert.equal(calls.length, 1)
    assert.equal(calls[0].init.method, 'GET')
})

test('feedback reports callback delivery accurately and preserves callback failures', async () => {
    const submissions = []
    const fetch = () => assert.fail('feedback must only use the configured callback')
    const input = { summary: 'Example feedback', feedback_type: 'mcp', sentiment: 'neutral' }
    const client = makeClient(fetch, {
        feedback: async (properties) => {
            submissions.push(properties)
        },
    })
    const result = await invoke(client, 'agent-feedback', input)
    assert.equal(result.data.received, true)
    assert.equal(submissions[0].feedback_summary, input.summary)
    assert.ok(Object.values(submissions[0]).every((value) => value !== undefined))
    assert.match(result.data.message, /configured SDK feedback callback/)
    await assert.rejects(invoke(makeClient(fetch), 'agent-feedback', input), /feedback callback/)
    const failing = makeClient(fetch, {
        feedback: async () => {
            throw new Error('Example sink failure')
        },
    })
    await assert.rejects(invoke(failing, 'agent-feedback', input), /Example sink failure/)
})

test('connected-project calls use the configured transport and keep the local project', async () => {
    const calls = []
    const target = {
        project_id: 42,
        project_name: 'Connected project',
        organization_id: 'connected-org',
        organization_name: 'Connected org',
        region: 'EU',
        base_url: 'https://eu.posthog.com',
    }
    const client = makeClient(async (url, init) => {
        calls.push({ url, init })
        assert.ok(url.startsWith('https://us.posthog.com/'))
        if (url.endsWith('/target/')) {
            return Response.json(target)
        }
        if (url.endsWith('/forward/')) {
            return Response.json({ status: 200, data: { results: [] } })
        }
        return Response.json({ results: [] })
    })
    const result = await invoke(client, 'posthog-connection-call', {
        connection_id: 'example-connection',
        tool: 'tasks-list',
    })
    assert.equal(result.data.ran_in.project_id, 42)
    const forwarded = JSON.parse(calls[1].init.body)
    assert.equal(forwarded.method, 'GET')
    assert.equal(forwarded.path, 'api/projects/42/tasks/')
    await invoke(client, 'tasks-list')
    assert.match(calls.at(-1).url, /\/api\/projects\/23\/tasks\//)
})
