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

    beforeEach(async () => {
        await tester.beforeEach()
    })

    const invokeAndGetFetch = async (
        inputs: Record<string, any>
    ): Promise<{
        invocation: Awaited<ReturnType<TemplateTester['invoke']>>['invocation']
        params: CyclotronInvocationQueueParametersFetchType
    }> => {
        const response = await tester.invoke(inputs, undefined, workflowOptions)
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
            idempotency_key: `${invocation.id}:action_1`,
        })
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
