import jwt from 'jsonwebtoken'

import { CyclotronInvocationQueueParametersFetchType } from '~/cdp/schema/cyclotron'
import { parseJSON } from '~/common/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './posthog-create-task.template'

describe('posthog create task template', () => {
    const tester = new TemplateTester(template)

    const workflowOptions = { hogFlow: { id: '0198c9f1-0000-0000-0000-000000000001' }, actionId: 'action_1' }
    const fullInputs = {
        prompt: 'Investigate the error spike in checkout',
        title: 'Checkout error spike',
        model: { model: 'claude-sonnet-5', reasoning_effort: 'high' },
        repository: 'example-org/example-repo',
        connectors: ['0198c9f1-aaaa-0000-0000-000000000001'],
        posthog_mcp_scopes: 'full',
        max_parallel_tasks: 3,
    }
    // Mirrors the default event in createGlobals; the request must always carry the trigger event.
    const defaultEventBody = {
        uuid: 'event-id',
        event: 'event-name',
        distinct_id: 'distinct-id',
        properties: { $current_url: 'https://example.com' },
        timestamp: '2024-01-01T00:00:00Z',
        elements_chain: '',
        url: 'https://us.posthog.com/projects/1/events/1234',
    }
    const slackMessageGlobals = (properties: Record<string, any> = {}): Record<string, any> => ({
        event: {
            event: '$slack_message_received',
            properties: {
                integration_id: 42,
                channel: 'C0ALERTS',
                ts: '1700000000.000100',
                thread_ts: null,
                user: 'U123',
                slack_team_id: 'T123',
                text: 'Database latency alert fired',
                ...properties,
            },
        },
    })

    beforeEach(async () => {
        await tester.beforeEach()
    })

    const invokeAndGetFetch = async (
        inputs: Record<string, any>,
        globals?: Record<string, any>
    ): Promise<{
        invocation: Awaited<ReturnType<TemplateTester['invoke']>>['invocation']
        params: CyclotronInvocationQueueParametersFetchType
    }> => {
        const response = await tester.invoke(inputs, globals, workflowOptions)
        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(false)
        return { invocation: response.invocation, params: response.invocation.queueParameters as any }
    }

    it('stages an authenticated create request with a step-scoped idempotency key', async () => {
        const { invocation, params } = await invokeAndGetFetch(fullInputs)

        expect(params.type).toBe('fetch')
        expect(params.method).toBe('POST')
        expect(params.url).toMatch(/\/api\/projects\/1\/workflow_tasks\/$/)

        const body = parseJSON(params.body!)
        expect(body).toEqual({
            prompt: 'Investigate the error spike in checkout',
            title: 'Checkout error spike',
            model: 'claude-sonnet-5',
            reasoning_effort: 'high',
            repository: 'example-org/example-repo',
            connectors: ['0198c9f1-aaaa-0000-0000-000000000001'],
            posthog_mcp_scopes: 'full',
            max_parallel_tasks: 3,
            event: defaultEventBody,
            idempotency_key: `${invocation.id}:action_1`,
        })

        const token = (params.headers?.['Authorization'] ?? '').replace('Bearer ', '')
        // The literal pins the cross-language contract: Django's TASKS_CREATE_JWT_SECRET dev default
        // (posthog/settings/data_stores.py) must match the nodejs one or local runs 401.
        // nosemgrep: javascript.jsonwebtoken.security.jwt-hardcode.hardcoded-jwt-secret
        const claims = jwt.verify(token, 'local-dev-tasks-create-jwt', {
            audience: 'posthog:tasks:create',
            algorithms: ['HS256'],
        }) as jwt.JwtPayload
        expect(claims.team_id).toBe(1)
        expect(claims.hog_flow_id).toBe(workflowOptions.hogFlow.id)
    })

    it('omits the fields without defaults when they are left empty', async () => {
        const { invocation, params } = await invokeAndGetFetch({ prompt: 'Do the thing' })

        expect(parseJSON(params.body!)).toEqual({
            prompt: 'Do the thing',
            posthog_mcp_scopes: 'read_only',
            max_parallel_tasks: 5,
            event: defaultEventBody,
            idempotency_key: `${invocation.id}:action_1`,
        })
    })

    it.each([
        ['a top-level post binds to its own ts', { thread_ts: null }, '1700000000.000100'],
        ['a thread reply binds to the parent thread', { thread_ts: '1699999999.000001' }, '1699999999.000001'],
    ])('sends slack context when triggered by a Slack message: %s', async (_name, properties, expectedThreadTs) => {
        const { params } = await invokeAndGetFetch(fullInputs, slackMessageGlobals(properties))

        // message_ts stays the triggering message's own ts even when thread_ts is the
        // parent, so the acknowledgement reaction lands on the message that fired the run.
        expect(parseJSON(params.body!).slack_context).toEqual({
            integration_id: 42,
            channel: 'C0ALERTS',
            thread_ts: expectedThreadTs,
            message_ts: '1700000000.000100',
            slack_user_id: 'U123',
            slack_team_id: 'T123',
            is_ext_shared_channel: false,
        })
    })

    it('forwards the externally shared channel flag so the backend can check approval', async () => {
        const { params } = await invokeAndGetFetch(fullInputs, slackMessageGlobals({ is_ext_shared_channel: true }))

        expect(parseJSON(params.body!).slack_context.is_ext_shared_channel).toEqual(true)
    })

    it('sends an empty slack user when a bot posted the triggering message', async () => {
        const { params } = await invokeAndGetFetch(fullInputs, slackMessageGlobals({ user: null }))

        expect(parseJSON(params.body!).slack_context.slack_user_id).toEqual('')
    })

    it('sends no slack context when the thread reply toggle is off', async () => {
        const { params } = await invokeAndGetFetch(
            { ...fullInputs, reply_in_slack_thread: false },
            slackMessageGlobals()
        )

        const body = parseJSON(params.body!)
        expect(body.slack_context).toBeUndefined()
        expect(body.event.event).toEqual('$slack_message_received')
    })

    it('sends no slack context for a non-Slack trigger even with the toggle on', async () => {
        const { params } = await invokeAndGetFetch({ ...fullInputs, reply_in_slack_thread: true })

        expect(parseJSON(params.body!).slack_context).toBeUndefined()
    })

    it('fails without staging a request when the instructions are empty', async () => {
        const response = await tester.invoke({ prompt: '' }, undefined, workflowOptions)
        expect(response.error).toMatch(/Instructions are required/)
        expect(response.invocation.queueParameters).toBeUndefined()
    })

    it('fails when invoked outside a workflow', async () => {
        const response = await tester.invoke(fullInputs)
        expect(response.error).toMatch(/inside a workflow/)
        expect(response.invocation.queueParameters).toBeUndefined()
    })

    it.each([[201], [200]])('returns the created task on a %i response', async (status) => {
        let response = await tester.invoke(fullInputs, undefined, workflowOptions)
        response = await tester.invokeFetchResponse(response.invocation, {
            status,
            body: { id: 'task-1', run_id: 'run-1' },
        })

        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(true)
        expect(response.execResult).toEqual({ id: 'task-1', run_id: 'run-1' })
    })

    it('skips instead of failing when the parallel task limit is hit', async () => {
        let response = await tester.invoke(fullInputs, undefined, workflowOptions)
        response = await tester.invokeFetchResponse(response.invocation, {
            status: 409,
            body: { detail: 'This workflow already has 3 tasks running' },
        })

        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(true)
        expect(response.execResult).toEqual({
            skipped: true,
            reason: 'This workflow already has 3 tasks running',
        })
        expect(response.logs.map((log) => log.message)).toContain(
            'Task not created: This workflow already has 3 tasks running'
        )
    })

    it.each([
        [400, 'Connector abc is not an active MCP connector'],
        [422, 'The workflow owner can no longer run tasks'],
    ])('surfaces the API error on a %i response', async (status, detail) => {
        let response = await tester.invoke(fullInputs, undefined, workflowOptions)
        response = await tester.invokeFetchResponse(response.invocation, { status, body: { detail } })

        expect(response.error).toEqual(`Failed to create task (${status}): ${detail}`)
    })

    it('declares 409 as a non-failure status so the engine does not fail the step before the code runs', () => {
        const entry = template.inputs_schema.find((input) => input.type === 'non_failure_status_codes')
        expect(entry?.default).toEqual([409])
    })
})
