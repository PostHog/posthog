import jwt from 'jsonwebtoken'

import { defaultConfig } from '~/common/config/config'
import { parseJSON } from '~/common/utils/json-parse'
import * as requestModule from '~/common/utils/request'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './posthog-create-customer-task.template'

describe('posthog create customer task template', () => {
    const tester = new TemplateTester(template)
    const workflowOptions = { hogFlow: { id: '0198c9f1-0000-0000-0000-000000000001' }, actionId: 'action_1' }

    const task = { id: '0198c9f1-0000-0000-0000-000000000003' }
    let fetchSpy: jest.SpyInstance
    const internalResponse = (status: number, body: unknown): requestModule.FetchResponse => ({
        status,
        headers: {},
        text: () => Promise.resolve(typeof body === 'string' ? body : JSON.stringify(body)),
        json: () => Promise.resolve(body),
        dump: async () => {},
    })
    beforeEach(async () => {
        await tester.beforeEach()
        fetchSpy = jest.spyOn(requestModule, 'internalFetch').mockResolvedValue(internalResponse(201, task))
    })
    afterEach(() => jest.restoreAllMocks())

    it.each([
        {
            name: 'Follow up',
            description: 'Arrange an onboarding session',
            account_id: '0198c9f1-0000-0000-0000-000000000002',
            assigned_to_id: '42',
            due_at: '2030-01-15T17:00:00Z',
        },
        { name: 'Follow up', description: '', account_id: '', due_at: '' },
    ])('calls the trusted internal API with task fields and workflow claims: %j', async (inputs) => {
        const response = await tester.invoke(inputs, undefined, workflowOptions)
        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(false)
        const resumed = await tester.resumeInvocation(response.invocation)
        expect(resumed.finished).toBe(true)
        expect(resumed.execResult).toEqual(task)
        expect(response.invocation.queueParameters).toBeUndefined()
        expect(fetchSpy).toHaveBeenCalledTimes(1)
        const [url, params] = fetchSpy.mock.calls[0] as [string, requestModule.FetchOptions]
        expect(params.method).toBe('POST')
        expect(url).toBe(`${defaultConfig.INTERNAL_API_BASE_URL}/api/projects/1/workflow_customer_tasks/`)
        const idempotencyKey = `${response.invocation.id}:action_1`
        expect(parseJSON(params.body!.toString())).toEqual({
            ...Object.fromEntries(Object.entries(inputs).filter(([, value]) => value !== '')),
            ...('assigned_to_id' in inputs ? { assigned_to_id: Number(inputs.assigned_to_id) } : {}),
            idempotency_key: idempotencyKey,
        })
        const claims = jwt.verify(
            new Headers(params.headers as Record<string, string>).get('authorization')!.replace('Bearer ', ''),
            defaultConfig.CUSTOMER_TASKS_CREATE_JWT_SECRET,
            {
                audience: 'posthog:customer-tasks:create',
                algorithms: ['HS256'],
            }
        ) as jwt.JwtPayload
        expect(claims).toMatchObject({
            team_id: 1,
            hog_flow_id: workflowOptions.hogFlow.id,
            idempotency_key: idempotencyKey,
        })
        expect(claims.exp! - claims.iat!).toBe(5 * 60)
    })

    it.each(['', '   '])('rejects a blank task name %j without creating a task', async (name) => {
        const response = await tester.invoke({ name }, undefined, workflowOptions)
        expect(response.error).toMatch(/Enter a task name/)
        expect(response.invocation.queueParameters).toBeUndefined()
    })

    it('rejects a fractional assignee ID without creating a task', async () => {
        const response = await tester.invoke({ name: 'Follow up', assigned_to_id: 1.5 }, undefined, workflowOptions)
        expect(response.error).toMatch(/valid numeric assignee user ID/)
        expect(response.invocation.queueParameters).toBeUndefined()
    })

    it('rejects invocation outside a workflow', async () => {
        const response = await tester.invoke({ name: 'Follow up' })
        expect(response.error).toMatch(/inside a workflow/)
        expect(response.invocation.queueParameters).toBeUndefined()
    })

    it.each([200, 201])('returns the task after a %i response', async (status) => {
        fetchSpy.mockResolvedValue(internalResponse(status, task))
        const invocation = await tester.invoke({ name: 'Follow up' }, undefined, workflowOptions)
        const response = await tester.resumeInvocation(invocation.invocation)
        expect(response.error).toBeUndefined()
        expect(response.execResult).toEqual(task)
    })

    it('reports backend validation errors', async () => {
        fetchSpy.mockResolvedValue(internalResponse(400, { detail: 'Assignee must be a project member' }))
        const invocation = await tester.invoke({ name: 'Follow up' }, undefined, workflowOptions)
        const response = await tester.resumeInvocation(invocation.invocation)
        expect(response.error).toEqual('Failed to create customer task (400): Assignee must be a project member')
    })

    it.each([
        [303, ''],
        [200, ''],
        [201, { status: 303, body: '' }],
        [201, { id: 'not-a-task-id' }],
    ])('rejects a redirect or malformed success (%i, %j)', async (status, body) => {
        fetchSpy.mockResolvedValue(internalResponse(status, body))
        const invocation = await tester.invoke({ name: 'Follow up' }, undefined, workflowOptions)
        const response = await tester.resumeInvocation(invocation.invocation)
        expect(response.error).toMatch(/Failed to create customer task/)
        expect(response.execResult).toBeUndefined()
    })
})
