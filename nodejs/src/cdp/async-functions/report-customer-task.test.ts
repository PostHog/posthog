import { defaultConfig } from '~/common/config/config'
import { parseJSON } from '~/common/utils/json-parse'
import * as requestModule from '~/common/utils/request'

import { createExampleInvocation } from '../_tests/fixtures'
import { AsyncFunctionContext, getAsyncFunctionHandler } from '../async-function-registry'
import { CyclotronJobInvocationHogFunctionContext, MinimalLogEntry } from '../types'
import { createInvocationResult } from '../utils/invocation-utils'
import './report-customer-task'

describe('postHogReportCustomerTask', () => {
    const customerTaskId = '0198c9f1-0000-0000-0000-000000000003'
    const payload = { customer_task_id: customerTaskId, report: 'Booked the onboarding call.', outcome: 'completed' }

    const invokeMock = (payload: Record<string, unknown>): any =>
        getAsyncFunctionHandler('postHogReportCustomerTask')!.mock([payload], [] as MinimalLogEntry[])

    const invokeLive = async (
        payload: Record<string, unknown>,
        state: Partial<CyclotronJobInvocationHogFunctionContext> = {}
    ): Promise<void> => {
        const invocation = {
            ...createExampleInvocation(),
            hogFlow: { id: 'flow-1' },
        }
        Object.assign(invocation.state, { actionId: 'action_1', ...state })
        await getAsyncFunctionHandler('postHogReportCustomerTask')!.execute(
            [payload],
            {
                invocation,
                internalApiBaseUrl: defaultConfig.INTERNAL_API_BASE_URL,
                consumeInlineAsyncBudget: () => {},
            } as unknown as AsyncFunctionContext,
            createInvocationResult<typeof invocation>(invocation)
        )
    }

    let fetchSpy: jest.SpyInstance
    beforeEach(() => {
        fetchSpy = jest.spyOn(requestModule, 'internalFetch').mockResolvedValue({
            status: 200,
            text: () => Promise.resolve(JSON.stringify({ id: customerTaskId })),
        } as requestModule.FetchResponse)
    })
    afterEach(() => jest.restoreAllMocks())

    // The step test panel mocks async functions by default. A mock body carrying fields the
    // endpoint never returns lets an author map an output that resolves to nothing live.
    it('returns only the canonical task ID from the mock', () => {
        expect(invokeMock({ ...payload, customer_task_id: customerTaskId.toUpperCase(), task_id: 'task-1' })).toEqual({
            status: 200,
            body: { id: customerTaskId },
        })
    })

    it.each([
        ['a missing task id', { ...payload, customer_task_id: undefined }, /Enter a customer task ID/],
        ['a malformed task id', { ...payload, customer_task_id: 'not-a-uuid' }, /valid customer task ID/],
        ['a blank report', { ...payload, report: '   ' }, /Enter a report/],
        ['an unknown outcome', { ...payload, outcome: 'later' }, /Choose an outcome/],
        ['a non-string AI task id', { ...payload, task_id: 42 }, /valid AI task ID/],
        ['a non-string AI task run id', { ...payload, task_run_id: true }, /valid AI task run ID/],
    ])('rejects %s in both mocked and live calls', async (_name, invalidPayload, expected) => {
        expect(() => invokeMock(invalidPayload)).toThrow(expected)
        await expect(invokeLive(invalidPayload)).rejects.toThrow(expected)
        expect(fetchSpy).not.toHaveBeenCalled()
    })

    it('lowercases the task id in the path and omits empty optional ids from the body', async () => {
        await invokeLive({
            ...payload,
            customer_task_id: customerTaskId.toUpperCase(),
            task_id: null,
            task_run_id: '',
        })

        expect(fetchSpy).toHaveBeenCalledTimes(1)
        const [url, params] = fetchSpy.mock.calls[0]
        expect(url).toContain(`/workflow_customer_tasks/${customerTaskId}/report/`)
        expect(parseJSON(params.body)).toEqual({ report: payload.report, outcome: 'completed' })
    })

    it.each([undefined, -1, 1.5, NaN])('rejects invalid versioned visit count %j', async (actionStepCount) => {
        await expect(invokeLive(payload, { customerTaskIdempotencyVersion: 1, actionStepCount })).rejects.toThrow(
            /valid workflow visit count/
        )
        expect(fetchSpy).not.toHaveBeenCalled()
    })
})
