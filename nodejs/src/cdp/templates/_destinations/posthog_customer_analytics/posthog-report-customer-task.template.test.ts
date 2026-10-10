import jwt from 'jsonwebtoken'

import { defaultConfig } from '~/common/config/config'
import { parseJSON } from '~/common/utils/json-parse'
import * as requestModule from '~/common/utils/request'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './posthog-report-customer-task.template'

describe('posthog report customer task template', () => {
    const tester = new TemplateTester(template)
    const workflowOptions = {
        hogFlow: { id: '0198c9f1-0000-0000-0000-000000000001' },
        actionId: 'action_1',
        actionStepCount: 3,
        customerTaskIdempotencyVersion: 1 as const,
    }

    const customerTaskId = '0198c9f1-0000-0000-0000-000000000003'
    const task = { id: customerTaskId }
    const requiredInputs = { customer_task_id: customerTaskId, report: 'Booked the onboarding call.' }
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
        fetchSpy = jest.spyOn(requestModule, 'internalFetch').mockResolvedValue(internalResponse(200, task))
    })
    afterEach(() => jest.restoreAllMocks())

    it.each([
        {
            ...requiredInputs,
            outcome: 'needs_human',
            task_id: '0198c9f1-0000-0000-0000-000000000004',
            task_run_id: '0198c9f1-0000-0000-0000-000000000005',
        },
        { ...requiredInputs, outcome: 'completed', task_id: '', task_run_id: '' },
        requiredInputs,
    ])('posts the report to the trusted internal API with workflow claims: %j', async (inputs) => {
        const response = await tester.invoke(inputs, undefined, workflowOptions)
        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(false)
        const resumed = await tester.resumeInvocation(response.invocation)
        expect(resumed.finished).toBe(true)
        expect(resumed.execResult).toEqual(task)
        expect(fetchSpy).toHaveBeenCalledTimes(1)
        const [url, params] = fetchSpy.mock.calls[0] as [string, requestModule.FetchOptions]
        expect(params.method).toBe('POST')
        expect(url).toBe(
            `${defaultConfig.INTERNAL_API_BASE_URL}/api/projects/1/workflow_customer_tasks/${customerTaskId}/report/`
        )
        expect(parseJSON(params.body!.toString())).toEqual({
            report: inputs.report,
            outcome: 'outcome' in inputs ? inputs.outcome : 'completed',
            ...('task_id' in inputs && inputs.task_id
                ? { task_id: inputs.task_id, task_run_id: inputs.task_run_id }
                : {}),
        })
        const claims = jwt.verify(
            new Headers(params.headers as Record<string, string>).get('authorization')!.replace('Bearer ', ''),
            defaultConfig.CUSTOMER_ANALYTICS_ACCOUNTS_JWT_SECRET,
            {
                audience: 'posthog:customer-tasks:report',
                algorithms: ['HS256'],
            }
        ) as jwt.JwtPayload
        expect(claims).toMatchObject({
            team_id: 1,
            hog_flow_id: workflowOptions.hogFlow.id,
            idempotency_key: `${response.invocation.id}:action_1:3`,
            customer_task_id: customerTaskId,
        })
        expect(claims.exp! - claims.iat!).toBe(5 * 60)
    })

    it.each([
        ['a missing customer task id', { report: 'Booked the call.' }, /Enter a customer task ID/],
        ['a blank report', { ...requiredInputs, report: '' }, /Enter a report/],
        ['an empty outcome', { ...requiredInputs, outcome: '' }, /Choose an outcome/],
    ])('rejects %s without sending a report', async (_name, inputs, expected) => {
        const response = await tester.invoke(inputs, undefined, workflowOptions)
        expect(response.error).toMatch(expected)
        expect(fetchSpy).not.toHaveBeenCalled()
    })

    it('rejects invocation outside a workflow', async () => {
        const response = await tester.invoke(requiredInputs)
        expect(response.error).toMatch(/inside a workflow/)
        expect(fetchSpy).not.toHaveBeenCalled()
    })

    it('reports backend validation errors', async () => {
        fetchSpy.mockResolvedValue(internalResponse(400, { detail: 'This task is already closed.' }))
        const invocation = await tester.invoke(requiredInputs, undefined, workflowOptions)
        const response = await tester.resumeInvocation(invocation.invocation)
        expect(response.error).toEqual('Failed to report to customer task (400): This task is already closed.')
    })

    it('rejects a redirect instead of treating it as success', async () => {
        fetchSpy.mockResolvedValue(internalResponse(303, ''))
        const invocation = await tester.invoke(requiredInputs, undefined, workflowOptions)
        const response = await tester.resumeInvocation(invocation.invocation)
        expect(response.error).toMatch(/Failed to report to customer task/)
        expect(response.execResult).toBeUndefined()
    })
})
